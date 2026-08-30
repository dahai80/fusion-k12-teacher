from __future__ import annotations

import json
import logging
from pathlib import Path

from .models import CurriculumStandard, KnowledgePoint

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"


class StandardsLoader:
    """课标数据加载器 — 从 JSON 文件加载课标知识点到内存。"""

    def __init__(self, data_dir: Path | None = None):
        self._data_dir = data_dir or DATA_DIR
        self._standards: dict[str, CurriculumStandard] = {}
        self._points_index: dict[str, KnowledgePoint] = {}
        self._loaded = False
        self._failed_files: list[str] = []

    def load_all(self) -> dict[str, CurriculumStandard]:
        """加载 data 目录下所有 JSON 课标文件。

        STD-8: 返 dict 快照(浅拷贝) — 防调用方改可变内部 _standards。
        与 STD-6 all_points/all_standards 同策略, 不用 MappingProxyType(活视图)。
        """
        if self._loaded:
            return dict(self._standards)

        if not self._data_dir.exists():
            logger.warning(f"课标数据目录不存在: {self._data_dir}")
            self._loaded = True
            return dict(self._standards)

        for json_file in sorted(self._data_dir.glob("*.json")):
            try:
                self._load_file(json_file)
            except Exception as e:
                self._failed_files.append(str(json_file))
                logger.error(f"加载课标文件失败 {json_file}: {e}")

        self._loaded = True
        logger.info(
            f"课标加载完成: {len(self._standards)} 个标准, {len(self._points_index)} 个知识点"
            + (f", 失败文件: {len(self._failed_files)}" if self._failed_files else "")
        )
        if self._failed_files:
            logger.warning("以下课标文件加载失败(已跳过): %s", self._failed_files)
        return dict(self._standards)

    @property
    def failed_files(self) -> list[str]:
        return list(self._failed_files)

    def _load_file(self, path: Path) -> None:
        """加载单个 JSON 课标文件。"""
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

    def _register(self, std: CurriculumStandard) -> None:
        """注册课标及其知识点到索引。"""
        self._standards[std.id] = std
        for kp in std.knowledge_points:
            self._points_index[kp.id] = kp

    def get_standard(self, std_id: str) -> CurriculumStandard | None:
        """按 ID 获取课标。"""
        if not self._loaded:
            self.load_all()
        return self._standards.get(std_id)

    def get_point(self, point_id: str) -> KnowledgePoint | None:
        """按 ID 获取知识点。"""
        if not self._loaded:
            self.load_all()
        return self._points_index.get(point_id)

    def all_points(self) -> dict[str, KnowledgePoint]:
        """返回所有知识点的快照(dict 浅拷贝, STD-6)。

        MappingProxyType 是活视图非快照 — reload()/迟注册 _register 改底层字典时,
        持有视图的消费者会见到突变或在迭代中 RuntimeError。快照隔离调用方。
        """
        if not self._loaded:
            self.load_all()
        return dict(self._points_index)

    def all_standards(self) -> dict[str, CurriculumStandard]:
        """返回所有课标的快照(dict 浅拷贝, STD-6)。见 all_points 说明。"""
        if not self._loaded:
            self.load_all()
        return dict(self._standards)

    def list_subjects(self) -> list[str]:
        """列出已加载的学科。"""
        if not self._loaded:
            self.load_all()
        return sorted({std.subject for std in self._standards.values() if std.subject})

    def list_grades(self, subject: str = "") -> list[str]:
        """列出已加载的年级。"""
        if not self._loaded:
            self.load_all()
        grades = set()
        for kp in self._points_index.values():
            if subject and kp.subject != subject:
                continue
            if kp.grade:
                grades.add(kp.grade)
        return sorted(grades, key=_grade_sort_key)

    def reload(self) -> dict[str, CurriculumStandard]:
        """强制重新加载。"""
        self._standards.clear()
        self._points_index.clear()
        self._loaded = False
        return self.load_all()


def _grade_sort_key(grade: str) -> int:
    """年级排序键。"""
    try:
        return int(grade)
    except ValueError:
        return 999
