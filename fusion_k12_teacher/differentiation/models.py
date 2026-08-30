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
        # E11: 显式列字段, 不再 `{k:v if v}` 丢弃假值 — 原 filter 丢空 extension/hints/exercises,
        # 下游无法区分"无拓展"与"字段缺失", 与 DifferentiatedContent 显式 to_dict 行为不一致。
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
    # E3: layers: dict[str, LayerContent] 替代 struggling/standard/advanced 三固定字段。
    # 原 3 字段与 E2 共同锁死三层, 新增层级须改 dataclass + to_dict + 全消费方 + 测试,
    # 扩展成本 O(全链路)。改 dict 后新增层级只需在 LEVEL_CONFIGS 登记。
    layers: dict[str, LayerContent] = field(default_factory=dict)
    group_tasks: list[GroupTask] = field(default_factory=list)
    standards_aligned: list[str] = field(default_factory=list)
    # R12: 分层生成失败时透出失败层与错误原因, 不再静默降级空层让教师拿无感知空内容。
    layer_errors: dict[str, str] = field(default_factory=dict)

    def get_layer(self, level: str) -> LayerContent:
        """按层级名取 LayerContent, 不存在返空 LayerContent (只读访问兼容)。"""
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
