from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Lesson:
    lesson: int = 0
    title: str = ""
    topic: str = ""
    knowledge_point_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "lesson": self.lesson,
            "title": self.title,
            "topic": self.topic,
            "knowledge_point_ids": self.knowledge_point_ids,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Lesson:
        return cls(
            lesson=int(data.get("lesson", 0) or 0),
            title=data.get("title", ""),
            topic=data.get("topic", data.get("title", "")),
            knowledge_point_ids=data.get("knowledge_point_ids", []),
        )


@dataclass
class Unit:
    unit: int = 0
    title: str = ""
    lessons: list[Lesson] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "unit": self.unit,
            "title": self.title,
            "lessons": [lesson.to_dict() for lesson in self.lessons],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Unit:
        return cls(
            unit=int(data.get("unit", 0) or 0),
            title=data.get("title", ""),
            lessons=[Lesson.from_dict(lesson) for lesson in data.get("lessons", [])],
        )


@dataclass
class TextbookEdition:
    edition: str = ""
    publisher: str = ""
    name: str = ""
    subject: str = ""
    grade_range: str = ""
    grades: dict[str, list[Unit]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "edition": self.edition,
            "publisher": self.publisher,
            "name": self.name,
            "subject": self.subject,
            "grade_range": self.grade_range,
            "grades": {
                g: [u.to_dict() for u in units] for g, units in self.grades.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TextbookEdition:
        grades: dict[str, list[Unit]] = {}
        for g, gdata in (data.get("grades") or {}).items():
            grades[str(g)] = [Unit.from_dict(u) for u in gdata.get("units", [])]
        return cls(
            edition=data.get("edition", ""),
            publisher=data.get("publisher", ""),
            name=data.get("name", ""),
            subject=data.get("subject", ""),
            grade_range=data.get("grade_range", ""),
            grades=grades,
        )
