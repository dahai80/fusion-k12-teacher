"""textbook module tests — loader index/grade/unit/lesson queries."""

from __future__ import annotations

import pytest

from fusion_k12_teacher.textbook.loader import TextbookLoader


@pytest.fixture
def loader():
    tl = TextbookLoader()
    tl.load_all()
    return tl


class TestDataIntegrity:
    """Textbook data integrity — every lesson must anchor a knowledge point, references must resolve in standards (#29)."""

    def test_every_lesson_has_knowledge_point(self, loader):
        # Any lesson in the data files with empty knowledge_point_ids → silent degradation of variation drills/graph anchoring
        weak = []
        for edition in loader.list_editions():
            ed = edition["edition"]
            for grade in loader.get_grades(ed, edition["subject"]):
                for unit in loader.get_units(ed, edition["subject"], grade):
                    for lesson in unit.lessons:
                        if not lesson.knowledge_point_ids:
                            weak.append(f"{ed}/g{grade} unit{unit.unit}-{lesson.lesson}《{lesson.title}》")
        assert weak == [], f"lessons missing knowledge point anchoring: {weak}"

    def test_kp_refs_resolve_in_standards(self, loader):
        # Referenced knowledge point ids must exist in the standards (math_g1-6.json) — dangling references = broken graph linkage
        import json
        from pathlib import Path
        std_path = Path(__file__).parent.parent / "fusion_k12_teacher" / "standards" / "data" / "math_g1-6.json"
        valid_ids = {kp["id"] for kp in json.loads(std_path.read_text(encoding="utf-8"))["knowledge_points"]}
        dangling = []
        for edition in loader.list_editions():
            ed = edition["edition"]
            for grade in loader.get_grades(ed, edition["subject"]):
                for unit in loader.get_units(ed, edition["subject"], grade):
                    for lesson in unit.lessons:
                        for kp_id in lesson.knowledge_point_ids:
                            if kp_id not in valid_ids:
                                dangling.append(f"{ed}/g{grade} {kp_id}")
        assert dangling == [], f"dangling knowledge point references: {dangling}"


class TestLoader:
    def test_loads_renjiao(self, loader):
        editions = loader.list_editions()
        assert any(e["edition"] == "renjiao" for e in editions)

    def test_failed_files_empty(self, loader):
        assert loader.failed_files == []

    def test_get_grades_math(self, loader):
        # i18n: user-facing
        grades = loader.get_grades("renjiao", "数学")
        assert "3" in grades
        assert "1" in grades
        assert len(grades) >= 6

    def test_get_grades_unknown(self, loader):
        # i18n: user-facing
        assert loader.get_grades("ghost", "数学") == []

    def test_get_units_g3(self, loader):
        # i18n: user-facing
        units = loader.get_units("renjiao", "数学", "3")
        assert len(units) >= 7
        u7 = next(u for u in units if u.unit == 7)
        assert u7.title == "分数的初步认识"

    def test_get_lesson_composite_id(self, loader):
        # i18n: user-facing
        unit, lesson = loader.get_lesson("renjiao", "数学", "3", "7-1")
        assert unit is not None
        assert lesson is not None
        assert lesson.title == "认识几分之一"
        assert lesson.topic == "分数的初步认识"

    def test_get_lesson_unknown(self, loader):
        # i18n: user-facing
        result = loader.get_lesson("renjiao", "数学", "3", "999-999")
        assert result is None

    def test_get_lesson_has_knowledge_points(self, loader):
        # i18n: user-facing
        _unit, lesson = loader.get_lesson("renjiao", "数学", "3", "7-1")
        assert lesson.knowledge_point_ids
        assert any(kp.startswith("math-g3") for kp in lesson.knowledge_point_ids)

    def test_reload(self, loader):
        result = loader.reload()
        assert "renjiao" in result
