"""textbook 模块测试 — loader 索引/年级/单元/课查询。"""

from __future__ import annotations

import pytest

from fusion_k12_teacher.textbook.loader import TextbookLoader


@pytest.fixture
def loader():
    tl = TextbookLoader()
    tl.load_all()
    return tl


class TestLoader:
    def test_loads_renjiao(self, loader):
        editions = loader.list_editions()
        assert any(e["edition"] == "renjiao" for e in editions)

    def test_failed_files_empty(self, loader):
        assert loader.failed_files == []

    def test_get_grades_math(self, loader):
        grades = loader.get_grades("renjiao", "数学")
        assert "3" in grades
        assert "1" in grades
        assert len(grades) >= 6

    def test_get_grades_unknown(self, loader):
        assert loader.get_grades("ghost", "数学") == []

    def test_get_units_g3(self, loader):
        units = loader.get_units("renjiao", "数学", "3")
        assert len(units) >= 7
        u7 = next(u for u in units if u.unit == 7)
        assert u7.title == "分数的初步认识"

    def test_get_lesson_composite_id(self, loader):
        unit, lesson = loader.get_lesson("renjiao", "数学", "3", "7-1")
        assert unit is not None
        assert lesson is not None
        assert lesson.title == "认识几分之一"
        assert lesson.topic == "分数的初步认识"

    def test_get_lesson_unknown(self, loader):
        result = loader.get_lesson("renjiao", "数学", "3", "999-999")
        assert result is None

    def test_get_lesson_has_knowledge_points(self, loader):
        _unit, lesson = loader.get_lesson("renjiao", "数学", "3", "7-1")
        assert lesson.knowledge_point_ids
        assert any(kp.startswith("math-g3") for kp in lesson.knowledge_point_ids)

    def test_reload(self, loader):
        result = loader.reload()
        assert "renjiao" in result
