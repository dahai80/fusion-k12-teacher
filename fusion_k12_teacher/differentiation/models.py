from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class LayerContent:
    explanation: str = ""
    examples: list[str] = field(default_factory=list)
    exercises: list[dict[str, Any]] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)
    extension: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v}


@dataclass
class GroupTask:
    group_name: str = ""
    task_description: str = ""
    expected_output: str = ""
    time_allocation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v}


@dataclass
class DifferentiatedContent:
    topic: str = ""
    grade: str = ""
    subject: str = ""
    struggling: LayerContent = field(default_factory=LayerContent)
    standard: LayerContent = field(default_factory=LayerContent)
    advanced: LayerContent = field(default_factory=LayerContent)
    group_tasks: list[GroupTask] = field(default_factory=list)
    standards_aligned: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "grade": self.grade,
            "subject": self.subject,
            "struggling": self.struggling.to_dict(),
            "standard": self.standard.to_dict(),
            "advanced": self.advanced.to_dict(),
            "group_tasks": [gt.to_dict() for gt in self.group_tasks],
            "standards_aligned": self.standards_aligned,
        }
