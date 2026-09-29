from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from .models import Lesson, TextbookEdition, Unit

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"


class TextbookLoader:
    """教材目录加载器 — 从 JSON 文件加载教材目录到内存。

    照抄 StandardsLoader 模式: 线程锁懒加载, 预建索引免全量扫描。
    索引: (edition, subject, grade) -> list[Unit]
    """

    def __init__(self, data_dir: Path | None = None):
        self._data_dir = data_dir or DATA_DIR
        self._editions: dict[str, TextbookEdition] = {}
        # (edition, subject, grade) -> list[Unit]
        self._esg_index: dict[tuple[str, str, str], list[Unit]] = {}
        self._loaded = False
        self._failed_files: list[str] = []
        self._load_lock = threading.Lock()

    def load_all(self) -> dict[str, TextbookEdition]:
        if self._loaded:
            return dict(self._editions)
        with self._load_lock:
            if self._loaded:
                return dict(self._editions)
            if not self._data_dir.exists():
                logger.warning("教材数据目录不存在: %s", self._data_dir)
                self._loaded = True
                return dict(self._editions)
            for json_file in sorted(self._data_dir.glob("*.json")):
                try:
                    self._load_file(json_file)
                except Exception as e:
                    self._failed_files.append(str(json_file))
                    logger.error("加载教材文件失败 %s: %s", json_file, e)
            self._rebuild_esg_index()
            self._loaded = True
            logger.info(
                "教材加载完成: %d 个版本, %d 个索引项",
                len(self._editions), len(self._esg_index),
            )
            if self._failed_files:
                logger.warning("以下教材文件加载失败(已跳过): %s", self._failed_files)
            return dict(self._editions)

    def _rebuild_esg_index(self) -> None:
        self._esg_index.clear()
        for ed in self._editions.values():
            for grade, units in ed.grades.items():
                key = (ed.edition, ed.subject, grade)
                self._esg_index[key] = list(units)

    def _load_file(self, path: Path) -> None:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        ed = TextbookEdition.from_dict(raw)
        if not ed.edition:
            ed.edition = path.stem
        self._editions[ed.edition] = ed

    @property
    def failed_files(self) -> list[str]:
        return list(self._failed_files)

    def list_editions(self) -> list[dict[str, Any]]:
        if not self._loaded:
            self.load_all()
        out: list[dict[str, Any]] = []
        for ed in self._editions.values():
            grades = sorted(ed.grades.keys(), key=_grade_sort_key)
            out.append({
                "edition": ed.edition,
                "name": ed.name,
                "publisher": ed.publisher,
                "subject": ed.subject,
                "grade_range": ed.grade_range,
                "grades": grades,
            })
        return out

    def get_edition(self, edition: str) -> TextbookEdition | None:
        if not self._loaded:
            self.load_all()
        return self._editions.get(edition)

    def get_grades(self, edition: str, subject: str) -> list[str]:
        if not self._loaded:
            self.load_all()
        ed = self._editions.get(edition)
        if not ed or ed.subject != subject:
            return []
        return sorted(ed.grades.keys(), key=_grade_sort_key)

    def get_units(self, edition: str, subject: str, grade: str) -> list[Unit]:
        if not self._loaded:
            self.load_all()
        return list(self._esg_index.get((edition, subject, grade), []))

    def get_lesson(
        self, edition: str, subject: str, grade: str, lesson_id: str
    ) -> tuple[Unit, Lesson] | None:
        # lesson_id 格式 "{unit}-{lesson}", 单元内课号不跨单元唯一, 故用复合 id。
        try:
            unit_num, lesson_num = lesson_id.split("-")
            unit_num, lesson_num = int(unit_num), int(lesson_num)
        except (ValueError, AttributeError):
            return None
        for unit in self.get_units(edition, subject, grade):
            if unit.unit != unit_num:
                continue
            for lesson in unit.lessons:
                if lesson.lesson == lesson_num:
                    return unit, lesson
        return None

    def reload(self) -> dict[str, TextbookEdition]:
        self._editions.clear()
        self._esg_index.clear()
        self._failed_files.clear()
        self._loaded = False
        return self.load_all()


def _grade_sort_key(grade: str) -> int:
    try:
        return int(grade)
    except ValueError:
        return 999
