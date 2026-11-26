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
        # E11: list fields explicitly, no more `{k:v if v}` dropping falsy values —
        # the old filter dropped empty extension/hints/exercises, so downstream
        # could not distinguish "no extension" from "field missing", inconsistent
        # with DifferentiatedContent's explicit to_dict behavior.
        return {
            "explanation": self.explanation,
            "examples": self.examples,
            "exercises": self.exercises,
            "hints": self.hints,
            "extension": self.extension,
        }


@dataclass
class GroupTask:
    group_name: str = ""
    task_description: str = ""
    expected_output: str = ""
    time_allocation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "group_name": self.group_name,
            "task_description": self.task_description,
            "expected_output": self.expected_output,
            "time_allocation": self.time_allocation,
        }


@dataclass
class DifferentiatedContent:
    topic: str = ""
    grade: str = ""
    subject: str = ""
    # E3: layers: dict[str, LayerContent] replaces the three fixed fields
    # struggling/standard/advanced. The old 3 fields, together with E2, locked in
    # exactly three layers; adding a layer required changing the dataclass +
    # to_dict + all consumers + tests — O(entire chain) extension cost. With a
    # dict, a new layer only needs registering in LEVEL_CONFIGS.
    layers: dict[str, LayerContent] = field(default_factory=dict)
    group_tasks: list[GroupTask] = field(default_factory=list)
    standards_aligned: list[str] = field(default_factory=list)
    # R12: when layer generation fails, surface the failed layer and error reason
    # instead of silently degrading to empty layers that give teachers
    # imperceptible empty content.
    layer_errors: dict[str, str] = field(default_factory=dict)

    # Get LayerContent by level name; return an empty LayerContent when missing
    #         (read-only access compatibility).
    def get_layer(self, level: str) -> LayerContent:
        return self.layers.get(level, LayerContent())

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "grade": self.grade,
            "subject": self.subject,
            "layers": {k: v.to_dict() for k, v in self.layers.items()},
            "group_tasks": [gt.to_dict() for gt in self.group_tasks],
            "standards_aligned": self.standards_aligned,
            "layer_errors": self.layer_errors,
        }
