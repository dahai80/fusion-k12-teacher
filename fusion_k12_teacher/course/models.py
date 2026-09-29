"""课程平台数据模型 — 学科无关的通用 DSL。

学科实现填充这些 dataclass, 平台/前端只认这些结构, 不认学科私有类型。
对应 PRD §5 FusionSocraticDSL + §12.3 SceneDSL, 抽象为学科中立的字段名。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class CheckpointType(StrEnum):
    MULTIPLE_CHOICE = "multiple_choice"
    NUMERIC_INPUT = "numeric_input"
    EXPRESSION = "expression"  # 代数式/方程等价判定 (学科 verifier 判)
    CANVAS_ACTION = "canvas_action"


class OnErrorAction(StrEnum):
    RETRY = "retry"
    REWIND = "rewind"
    SHOW_HINT = "show_hint"
    JUMP = "jump"


@dataclass
class Checkpoint:
    """随堂互动卡点 — 苏格拉底式不直接给答案。"""
    id: str
    type: CheckpointType
    prompt: str
    options: list[dict[str, Any]] = field(default_factory=list)
    expected_expression: str = ""  # 学科符号引擎判等 (数学=SymPy, 物理=SymPy, 语言=字符串)
    expected_value: float = 0.0
    tolerance: float = 0.01
    hints: list[str] = field(default_factory=list)
    on_error_action: OnErrorAction = OnErrorAction.RETRY
    target_prerequisite_id: str = ""
    difficulty_layer: str = "B"  # A 基础 | B 进阶 | C 拔高

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "type": self.type.value, "prompt": self.prompt,
            "options": self.options, "expected_expression": self.expected_expression,
            "expected_value": self.expected_value, "tolerance": self.tolerance,
            "hints": self.hints, "on_error_action": self.on_error_action.value,
            "target_prerequisite_id": self.target_prerequisite_id,
            "difficulty_layer": self.difficulty_layer,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Checkpoint:
        ctype = d.get("type", "multiple_choice")
        try:
            ctype = CheckpointType(ctype)
        except ValueError:
            ctype = CheckpointType.MULTIPLE_CHOICE
        on_err = d.get("on_error_action", "retry")
        try:
            on_err = OnErrorAction(on_err)
        except ValueError:
            on_err = OnErrorAction.RETRY
        return cls(
            id=str(d.get("id", "")), type=ctype, prompt=str(d.get("prompt", ""))[:500],
            options=[dict(o) for o in d.get("options", []) if isinstance(o, dict)][:6],
            expected_expression=str(d.get("expected_expression", d.get("expected_sympy", ""))),
            expected_value=float(d.get("expected_value", 0) or 0),
            tolerance=float(d.get("tolerance", 0.01)),
            hints=[str(h) for h in d.get("hints", [])][:4],
            on_error_action=on_err,
            target_prerequisite_id=str(d.get("target_prerequisite_id", "")),
            difficulty_layer=str(d.get("difficulty_layer", "B")),
        )


@dataclass
class AnimationSegment:
    start_ratio: float = 0.0
    end_ratio: float = 1.0
    camera_focus_entity: str = ""
    highlight_entities: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_ratio": self.start_ratio, "end_ratio": self.end_ratio,
            "camera_focus_entity": self.camera_focus_entity,
            "highlight_entities": self.highlight_entities,
        }


@dataclass
class Landmark:
    time_offset_ms: int = 0
    progress_ratio: float = 0.0
    latex_highlight_var: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "timeOffsetMs": self.time_offset_ms,
            "progressRatio": self.progress_ratio,
            "latexHighlightVar": self.latex_highlight_var,
        }


@dataclass
class TeachingStep:
    """5E 课稿步骤 — 学科中立。phase ∈ Engage/Explore/Explain/Elaborate/Evaluate/Transfer。"""
    step_id: str
    step_title: str
    speech_narration: str
    phase: str = ""
    landmarks: list[Landmark] = field(default_factory=list)
    animation: AnimationSegment = field(default_factory=AnimationSegment)
    checkpoint: Checkpoint | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id, "step_title": self.step_title, "phase": self.phase,
            "speech_narration": self.speech_narration,
            "landmarks": [lm.to_dict() for lm in self.landmarks],
            "animation": self.animation.to_dict(),
            "checkpoint": self.checkpoint.to_dict() if self.checkpoint else None,
        }


@dataclass
class FusionSocraticDSL:
    """苏格拉底课稿 DSL v2.1.0 — 学科中立。"""
    version: str = "2.1.0"
    subject: str = ""
    meta: dict[str, str] = field(default_factory=dict)
    global_variables: dict[str, dict[str, Any]] = field(default_factory=dict)
    steps: list[TeachingStep] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version, "subject": self.subject, "meta": self.meta,
            "global_variables": self.global_variables,
            "steps": [s.to_dict() for s in self.steps],
            "error": self.error,
        }


@dataclass
class SceneEntity:
    id: str
    type: str = "moving_object"  # moving_object | static_structure | reference_line | curve
    label: str = ""
    value: float = 0.0
    unit: str = ""
    color: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "type": self.type, "label": self.label,
                "value": self.value, "unit": self.unit, "color": self.color}


@dataclass
class Milestone:
    progress_percentage: float
    time_mark: float
    event_name: str
    highlight_entities: list[str] = field(default_factory=list)
    formula_state: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "progress_percentage": self.progress_percentage, "time_mark": self.time_mark,
            "event_name": self.event_name, "highlight_entities": self.highlight_entities,
            "formula_state": self.formula_state,
        }


@dataclass
class SceneDSL:
    """场景动画 DSL — 学科中立 (PRD §12.3 schema 抽象)。"""
    version: str = "2.0.0"
    subject: str = ""
    template_type: str = ""
    meta: dict[str, str] = field(default_factory=dict)
    entities: list[dict[str, Any]] = field(default_factory=list)
    canvas_config: dict[str, Any] = field(default_factory=dict)
    timeline: dict[str, Any] = field(default_factory=dict)
    pedagogy: dict[str, Any] = field(default_factory=dict)
    verified: bool = False
    error: str = ""
    fallback: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version, "subject": self.subject, "template_type": self.template_type,
            "meta": self.meta, "entities": self.entities, "canvas_config": self.canvas_config,
            "timeline": self.timeline, "pedagogy": self.pedagogy,
            "verified": self.verified, "error": self.error, "fallback": self.fallback,
        }


@dataclass
class VerifyResult:
    """学科 verifier 校验结果。"""
    verified: bool = False
    variables: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    fallback: bool = False


@dataclass
class JudgeResult:
    """checkpoint 判分结果 — 学科中立。"""
    correct: bool
    method: str = ""  # "verifier" | "numeric" | "string_fallback" | "multiple_choice"
    detail: str = ""
    fallback: bool = False
    hint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "correct": self.correct, "method": self.method, "detail": self.detail,
            "fallback": self.fallback, "hint": self.hint,
        }


@dataclass
class GraphNode:
    """知识图谱节点 — 学科中立 (PRD §3.2 schema 抽象)。"""
    id: str
    title: str
    node_type: str = "Concept"  # Concept | Theorem | Method | Misconception
    stage: str = ""
    strand: str = ""
    grade: str = ""
    spatial: dict[str, float] = field(default_factory=dict)
    visual_engine: str = ""
    formula: str = ""
    misconceptions: list[str] = field(default_factory=list)
    cognitive_level: str = ""
    description: str = ""
    curriculum_code: str = ""
    edges: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "title": self.title, "node_type": self.node_type,
            "stage": self.stage, "strand": self.strand, "grade": self.grade,
            "spatial": self.spatial, "visual_engine": self.visual_engine,
            "formula": self.formula, "misconceptions": self.misconceptions,
            "cognitive_level": self.cognitive_level, "description": self.description,
            "curriculum_code": self.curriculum_code, "edges": self.edges,
        }


@dataclass
class CoursePackage:
    """课程包 — 学科中立, 供课堂编排。"""
    class_id: str
    subject: str
    grade: str
    topic: str
    materials: dict[str, Any] = field(default_factory=dict)
    code: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "class_id": self.class_id, "subject": self.subject, "grade": self.grade,
            "topic": self.topic, "materials": self.materials, "code": self.code,
        }
