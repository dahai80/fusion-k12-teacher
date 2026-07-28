from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class KnowledgePoint:
    id: str = ""
    subject: str = ""
    grade: str = ""
    strand: str = ""
    topic: str = ""
    description: str = ""
    prerequisites: List[str] = field(default_factory=list)
    progression_next: List[str] = field(default_factory=list)
    difficulty_level: str = "standard"
    curriculum_code: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "subject": self.subject,
            "grade": self.grade,
            "strand": self.strand,
            "topic": self.topic,
            "description": self.description,
            "prerequisites": self.prerequisites,
            "progression_next": self.progression_next,
            "difficulty_level": self.difficulty_level,
            "curriculum_code": self.curriculum_code,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> KnowledgePoint:
        return cls(
            id=data.get("id", ""),
            subject=data.get("subject", ""),
            grade=data.get("grade", ""),
            strand=data.get("strand", ""),
            topic=data.get("topic", ""),
            description=data.get("description", ""),
            prerequisites=data.get("prerequisites", []),
            progression_next=data.get("progression_next", []),
            difficulty_level=data.get("difficulty_level", "standard"),
            curriculum_code=data.get("curriculum_code", ""),
        )


@dataclass
class CurriculumStandard:
    id: str = ""
    name: str = ""
    year: str = ""
    subject: str = ""
    grade_range: str = ""
    knowledge_points: List[KnowledgePoint] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "year": self.year,
            "subject": self.subject,
            "grade_range": self.grade_range,
            "knowledge_points": [kp.to_dict() for kp in self.knowledge_points],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CurriculumStandard:
        kps = [KnowledgePoint.from_dict(kp) for kp in data.get("knowledge_points", [])]
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            year=data.get("year", ""),
            subject=data.get("subject", ""),
            grade_range=data.get("grade_range", ""),
            knowledge_points=kps,
        )


@dataclass
class AlignmentContext:
    knowledge_points: List[KnowledgePoint] = field(default_factory=list)
    prerequisites: List[List[KnowledgePoint]] = field(default_factory=list)
    curriculum_codes: List[str] = field(default_factory=list)
    suggested_objectives: List[str] = field(default_factory=list)
    must_cover: List[str] = field(default_factory=list)
    optional_advanced: List[str] = field(default_factory=list)


@dataclass
class CoverageReport:
    subject: str = ""
    grade: str = ""
    total_points: int = 0
    covered_points: int = 0
    coverage_ratio: float = 0.0
    missing_points: List[str] = field(default_factory=list)
    details: List[Dict[str, Any]] = field(default_factory=list)
