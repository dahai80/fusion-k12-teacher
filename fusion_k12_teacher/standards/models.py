from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_SUPPORTED_SCHEMA_VERSIONS = {"1.0"}


def _migrate_standard(data: dict[str, Any], version: str) -> dict[str, Any]:
    """E7: curriculum standard schema version migration — explicit field-layout conversion between known
    versions, instead of the loader silently skipping the whole file.

    When adding a new schema version, register its migration function here: map the new version's
    fields back to the v1.0 layout and load as v1.0, avoiding "when the standard schema upgrades to
    2.0, all new-format files get silently dropped and the standards vanish at runtime with no error".
    Unknown versions (no migration path) still raise ValueError so the loader records the failed file explicitly.
    """
    if version == "1.0":
        return data
    # Extend future version migrations here, e.g.:
    # if version == "2.0":
    #     data = _migrate_1_to_2(data)  # field renames/regrouping
    #     return data
    raise ValueError(
        f"curriculum standard {data.get('id', '?')} schema_version={version} not supported"
        f"(known: {sorted(_SUPPORTED_SCHEMA_VERSIONS)}), no migration path, refusing to load to avoid data corruption"
    )
# STD-9: difficulty_level enum whitelist — a typo (basik) would be treated as non-basic, aligner never enforces must_cover.
_VALID_DIFFICULTY_LEVELS = {"basic", "standard", "advanced"}


@dataclass
class KnowledgePoint:
    id: str = ""
    subject: str = ""
    grade: str = ""
    strand: str = ""
    topic: str = ""
    description: str = ""
    prerequisites: list[str] = field(default_factory=list)
    progression_next: list[str] = field(default_factory=list)
    difficulty_level: str = "standard"
    curriculum_code: str = ""

    def to_dict(self) -> dict[str, Any]:
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
    def from_dict(cls, data: dict[str, Any]) -> KnowledgePoint:
        # STD-9: validate difficulty_level enum — invalid values (typo/empty) log a warning and fall back to standard,
        # avoiding the aligner treating a typo as non-basic and excluding it from must_cover forever.
        difficulty = data.get("difficulty_level", "standard")
        if difficulty not in _VALID_DIFFICULTY_LEVELS:
            logger.warning(
                "knowledge point %s difficulty_level=%r invalid (must be one of %s), falling back to standard",
                data.get("id", "?"), difficulty, sorted(_VALID_DIFFICULTY_LEVELS),
            )
            difficulty = "standard"
        return cls(
            id=data.get("id", ""),
            subject=data.get("subject", ""),
            grade=data.get("grade", ""),
            strand=data.get("strand", ""),
            topic=data.get("topic", ""),
            description=data.get("description", ""),
            prerequisites=data.get("prerequisites", []),
            progression_next=data.get("progression_next", []),
            difficulty_level=difficulty,
            curriculum_code=data.get("curriculum_code", ""),
        )


@dataclass
class CurriculumStandard:
    id: str = ""
    name: str = ""
    year: str = ""
    subject: str = ""
    grade_range: str = ""
    knowledge_points: list[KnowledgePoint] = field(default_factory=list)
    schema_version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "year": self.year,
            "subject": self.subject,
            "grade_range": self.grade_range,
            "knowledge_points": [kp.to_dict() for kp in self.knowledge_points],
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CurriculumStandard:
        kps = [KnowledgePoint.from_dict(kp) for kp in data.get("knowledge_points", [])]
        ver = data.get("schema_version", "")
        if not ver:
            logger.warning(
                "curriculum standard %s has no schema_version field, loading as legacy format (v1.0); fields may be missing after upgrade",
                data.get("id", "?"),
            )
            ver = "1.0"
        # STD-7/E7: known versions go through explicit migration functions; unknown versions with no
        # migration path raise ValueError so the loader records the failed file explicitly, rather than
        # silently skipping the whole file and the standard vanishing without a trace.
        data = _migrate_standard(data, ver)
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            year=data.get("year", ""),
            subject=data.get("subject", ""),
            grade_range=data.get("grade_range", ""),
            knowledge_points=kps,
            schema_version=ver,
        )


@dataclass
class AlignmentContext:
    knowledge_points: list[KnowledgePoint] = field(default_factory=list)
    prerequisites: list[list[KnowledgePoint]] = field(default_factory=list)
    curriculum_codes: list[str] = field(default_factory=list)
    suggested_objectives: list[str] = field(default_factory=list)
    must_cover: list[str] = field(default_factory=list)
    optional_advanced: list[str] = field(default_factory=list)


@dataclass
class CoverageReport:
    subject: str = ""
    grade: str = ""
    total_points: int = 0
    covered_points: int = 0
    coverage_ratio: float = 0.0
    missing_points: list[str] = field(default_factory=list)
    details: list[dict[str, Any]] = field(default_factory=list)
