from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from .models import CurriculumStandard, KnowledgePoint

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"


# Curriculum standards loader — loads standards knowledge points from JSON files into memory.
class StandardsLoader:

    def __init__(self, data_dir: Path | None = None):
        self._data_dir = data_dir or DATA_DIR
        self._standards: dict[str, CurriculumStandard] = {}
        self._points_index: dict[str, KnowledgePoint] = {}
        # E6: (subject, grade) -> list[KnowledgePoint] index, so get_knowledge_points skips the full scan.
        self._sg_index: dict[tuple[str, str], list[KnowledgePoint]] = {}
        self._loaded = False
        self._failed_files: list[str] = []
        # R11: threading.Lock guards the lazy-load critical section — when an async server's first
        # requests fire concurrently, multiple coroutines calling _load_file/_register would
        # double-load and transiently double-register.
        self._load_lock = threading.Lock()

    # Loads all JSON curriculum standards files under the data directory.
    #
    #         STD-8: returns a dict snapshot (shallow copy) — prevents callers from mutating the internal _standards.
    #         Same strategy as STD-6 all_points/all_standards, no MappingProxyType (live view).
    #         R11: lock guards the check-then-set, avoiding duplicate loading on concurrent first load.
    def load_all(self) -> dict[str, CurriculumStandard]:
        if self._loaded:
            return dict(self._standards)

        with self._load_lock:
            # double-check: another thread may have finished loading while we waited for the lock
            if self._loaded:
                return dict(self._standards)

            if not self._data_dir.exists():
                logger.warning(f"standards data directory does not exist: {self._data_dir}")
                self._loaded = True
                return dict(self._standards)

            for json_file in sorted(self._data_dir.glob("*.json")):
                try:
                    self._load_file(json_file)
                except Exception as e:
                    self._failed_files.append(str(json_file))
                    logger.error(f"failed to load standards file {json_file}: {e}")

            # E6: build the (subject, grade) index after the scan
            self._rebuild_sg_index()

            self._loaded = True
            logger.info(
                f"standards load complete: {len(self._standards)} standards, {len(self._points_index)} knowledge points"
                + (f", failed files: {len(self._failed_files)}" if self._failed_files else "")
            )
            if self._failed_files:
                logger.warning("the following standards files failed to load (skipped): %s", self._failed_files)
            return dict(self._standards)

    # E6: builds the (subject, grade) -> list[KnowledgePoint] index.
    def _rebuild_sg_index(self) -> None:
        self._sg_index.clear()
        for kp in self._points_index.values():
            key = (kp.subject, kp.grade)
            self._sg_index.setdefault(key, []).append(kp)
        for pts in self._sg_index.values():
            pts.sort(key=lambda k: k.id)

    @property
    def failed_files(self) -> list[str]:
        return list(self._failed_files)

    # Loads a single JSON standards file.
    def _load_file(self, path: Path) -> None:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)

        if isinstance(raw, list):
            for item in raw:
                std = CurriculumStandard.from_dict(item)
                self._register(std)
        elif isinstance(raw, dict):
            if "knowledge_points" in raw:
                std = CurriculumStandard.from_dict(raw)
                self._register(std)
            else:
                std_id = raw.get("id", path.stem)
                points = []
                for kp_data in raw.get("points", []):
                    kp_data.setdefault("subject", raw.get("subject", ""))
                    kp_data.setdefault("grade", raw.get("grade", ""))
                    points.append(KnowledgePoint.from_dict(kp_data))
                std = CurriculumStandard(
                    id=std_id,
                    name=raw.get("name", path.stem),
                    year=raw.get("year", ""),
                    subject=raw.get("subject", ""),
                    grade_range=raw.get("grade_range", ""),
                    knowledge_points=points,
                )
                self._register(std)

    # Registers a standard and its knowledge points into the indexes.
    def _register(self, std: CurriculumStandard) -> None:
        self._standards[std.id] = std
        for kp in std.knowledge_points:
            self._points_index[kp.id] = kp

    # E6: fetches knowledge points by (subject, grade) index, returns a snapshot list, no full scan.
    #
    #         Reused by StandardsQuery.get_knowledge_points — previously each call shallow-copied the whole
    #         all_points() dict and filtered O(N); now goes through the prebuilt index, sorted by id.
    def get_knowledge_points(self, subject: str, grade: str) -> list[KnowledgePoint]:
        if not self._loaded:
            self.load_all()
        pts = self._sg_index.get((subject, grade), [])
        return list(pts)

    # Fetches a standard by ID.
    def get_standard(self, std_id: str) -> CurriculumStandard | None:
        if not self._loaded:
            self.load_all()
        return self._standards.get(std_id)

    # Fetches a knowledge point by ID.
    def get_point(self, point_id: str) -> KnowledgePoint | None:
        if not self._loaded:
            self.load_all()
        return self._points_index.get(point_id)

    # Returns a snapshot of all knowledge points (dict shallow copy, STD-6).
    #
    #         MappingProxyType is a live view, not a snapshot — when reload()/late _register mutates the
    #         underlying dict, consumers holding the view see mutations or hit RuntimeError during
    #         iteration. Snapshots isolate callers.
    def all_points(self) -> dict[str, KnowledgePoint]:
        if not self._loaded:
            self.load_all()
        return dict(self._points_index)

    # Returns a snapshot of all standards (dict shallow copy, STD-6). See all_points.
    def all_standards(self) -> dict[str, CurriculumStandard]:
        if not self._loaded:
            self.load_all()
        return dict(self._standards)

    # Lists loaded subjects.
    def list_subjects(self) -> list[str]:
        if not self._loaded:
            self.load_all()
        return sorted({std.subject for std in self._standards.values() if std.subject})

    # Lists loaded grades.
    def list_grades(self, subject: str = "") -> list[str]:
        if not self._loaded:
            self.load_all()
        grades = set()
        for kp in self._points_index.values():
            if subject and kp.subject != subject:
                continue
            if kp.grade:
                grades.add(kp.grade)
        return sorted(grades, key=_grade_sort_key)

    # Force-reloads all standards.
    def reload(self) -> dict[str, CurriculumStandard]:
        self._standards.clear()
        self._points_index.clear()
        # R10: clear the failed-files list — the old reload did not clear it, so stale failure
        # entries accumulated across reloads; fixed files kept reporting failures and
        # failed_files stayed permanently wrong.
        self._failed_files.clear()
        self._sg_index.clear()
        self._loaded = False
        return self.load_all()


# Grade sort key.
def _grade_sort_key(grade: str) -> int:
    try:
        return int(grade)
    except ValueError:
        return 999
