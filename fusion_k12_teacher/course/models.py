"""课程平台数据模型 — 学科无关的通用 DSL。

学科实现填充这些 dataclass, 平台/前端只认这些结构, 不认学科私有类型。
对应 PRD §5 FusionSocraticDSL + §12.3 SceneDSL, 抽象为学科中立的字段名。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


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


# issue #19: DSL v3.0 — 8 可视化基元 (visual_type 路由)
class VisualType(StrEnum):
    ARRAY_GRID = "array_grid"            # 1-2年级 计数/圈画/阵列
    TAPE_DIAGRAM = "tape_diagram"        # 2-6年级 和差倍比/分数 (核心通用)
    GEOMETRY_2D = "geometry_2d"          # 3-5年级 平面几何/周长面积
    ISOMETRIC_3D = "isometric_3d"        # 5-6年级 立体几何/切削展开
    TRACK_TIMELINE = "track_timeline"    # 4-6年级 速度/时间/行程追及
    BUCKET_DIVIDER = "bucket_divider"    # 4-6年级 组合/隔板/抽屉原理
    DATA_CHART = "data_chart"            # 4-5年级 统计/条形/折线图
    FLOW_CARD = "flow_card"              # 纯计算/方程/通用兜底


# issue #19: DSL v3.0 — 二级兜底基元 (fallback_type)
class FallbackType(StrEnum):
    TAPE_DIAGRAM = "tape_diagram"
    FLOW_CARD = "flow_card"


VISUAL_TYPES = tuple(v.value for v in VisualType)
FALLBACK_TYPES = tuple(v.value for v in FallbackType)


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
class VisualState:
    """issue #19: DSL v3.0 — 步骤级可视化状态 (visual_type 路由驱动)。"""
    visual_type: str = ""
    action: str = ""
    progress_range: tuple[float, float] = (0.0, 1.0)
    active_entities: list[str] = field(default_factory=list)
    latex_state: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "visual_type": self.visual_type, "action": self.action,
            "progress_range": list(self.progress_range),
            "active_entities": self.active_entities,
            "latex_state": self.latex_state,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> VisualState:
        vt = str(d.get("visual_type", ""))
        if vt and vt not in VISUAL_TYPES:
            logger.warning("visual_type 不在白名单: %s -> flow_card 兜底", vt)
            vt = VisualType.FLOW_CARD.value
        pr = d.get("progress_range", [0.0, 1.0])
        if not isinstance(pr, (list, tuple)) or len(pr) != 2:
            pr = (0.0, 1.0)
        else:
            pr = (float(pr[0]), float(pr[1]))
        return cls(
            visual_type=vt, action=str(d.get("action", ""))[:200],
            progress_range=pr,
            active_entities=[str(e) for e in d.get("active_entities", [])][:20],
            latex_state=str(d.get("latex_state", ""))[:500],
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
    visual_state: VisualState = field(default_factory=VisualState)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id, "step_title": self.step_title, "phase": self.phase,
            "speech_narration": self.speech_narration,
            "landmarks": [lm.to_dict() for lm in self.landmarks],
            "animation": self.animation.to_dict(),
            "checkpoint": self.checkpoint.to_dict() if self.checkpoint else None,
            "visual_state": self.visual_state.to_dict(),
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
    """场景动画 DSL — 学科中立 (PRD §12.3 schema 抽象)。

    issue #19 v3.0: 作为 FusionSocraticDSL.scene 的类型化子合约,
    不再是独立平级模型。scene_compiler 仍可返回 SceneDSL (向后兼容),
    但 FusionSocraticDSL.scene 字段持有 SceneDSL 实例实现统一合约。
    """
    version: str = "3.0.0"
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
class FusionSocraticDSL:
    """苏格拉底课稿 DSL v3.0 — 学科中立 (issue #19)。

    v3.0 变更:
    - meta 新增 visual_type (8 基元路由) + fallback_type (2 兜底)
    - step.visual_state 携带步骤级可视化动作
    - scene 字段为 SceneDSL 类型 (统一 v3.0 合约, 不再是 plain dict)
    - to_spec_dict() 输出符合 spec DSL v3.0 JSON Schema (fusion-core SOCRATIC_DSL_V3_SCHEMA)
    """
    version: str = "3.0.0"
    subject: str = ""
    meta: dict[str, str] = field(default_factory=dict)
    global_variables: dict[str, dict[str, Any]] = field(default_factory=dict)
    steps: list[TeachingStep] = field(default_factory=list)
    scene: SceneDSL = field(default_factory=SceneDSL)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version, "subject": self.subject, "meta": self.meta,
            "global_variables": self.global_variables,
            "steps": [s.to_dict() for s in self.steps],
            "scene": self.scene.to_dict() if isinstance(self.scene, SceneDSL) else self.scene,
            "error": self.error,
        }

    def to_spec_dict(self) -> dict[str, Any]:
        """issue #19 P0: 转换为 spec DSL v3.0 JSON Schema 合规结构。

        spec (architecture/k12-train-model-autumation-1009.md §417-432) 要求根级
        required: ["meta", "parameters", "entities", "pipeline"], additionalProperties=False。
        fusion-core SOCRATIC_DSL_V3_SCHEMA 与此一致 (core#26)。

        字段映射:
          meta:         内部 meta + backfill id/grade/topic/visual_type/fallback_type
          parameters:   global_variables → {label, value, unit} (value 强制 float)
          entities:     scene.entities → {id, type, label, properties}
          pipeline:     steps → {step, title, formula, eval, result_unit, visual_state}
        """
        meta_out = self._spec_meta()
        params_out = self._spec_parameters()
        entities_out = self._spec_entities()
        pipeline_out = self._spec_pipeline()
        return {
            "meta": meta_out,
            "parameters": params_out,
            "entities": entities_out,
            "pipeline": pipeline_out,
        }

    def _spec_meta(self) -> dict[str, Any]:
        m = self.meta if isinstance(self.meta, dict) else {}
        vt = str(m.get("visual_type", VisualType.FLOW_CARD.value))
        if vt not in VISUAL_TYPES:
            vt = VisualType.FLOW_CARD.value
        fb = str(m.get("fallback_type", FallbackType.TAPE_DIAGRAM.value))
        if fb not in FALLBACK_TYPES:
            fb = FallbackType.TAPE_DIAGRAM.value
        grade_raw = m.get("grade", "5")
        try:
            grade_num = float(grade_raw)
        except (TypeError, ValueError):
            grade_num = 5.0
        return {
            "id": str(m.get("knowledge_node_id", m.get("id", ""))),
            "grade": grade_num,
            "topic": str(m.get("title", m.get("topic", ""))),
            "visual_type": vt,
            "fallback_type": fb,
        }

    def _spec_parameters(self) -> dict[str, dict[str, Any]]:
        gvars = self.global_variables if isinstance(self.global_variables, dict) else {}
        out: dict[str, dict[str, Any]] = {}
        for key, val in gvars.items():
            if not isinstance(val, dict):
                val = {"value": val}
            try:
                v = float(val.get("value", 0) or 0)
            except (TypeError, ValueError):
                v = 0.0
            out[str(key)] = {
                "label": str(val.get("label", str(key))),
                "value": v,
                "unit": str(val.get("unit", "")),
            }
        return out

    def _spec_entities(self) -> list[dict[str, Any]]:
        scene_entities = []
        if isinstance(self.scene, SceneDSL):
            scene_entities = self.scene.entities if isinstance(self.scene.entities, list) else []
        elif isinstance(self.scene, dict):
            scene_entities = self.scene.get("entities", []) if isinstance(self.scene.get("entities"), list) else []
        out: list[dict[str, Any]] = []
        for ent in scene_entities:
            if not isinstance(ent, dict):
                continue
            eid = str(ent.get("id", ""))
            if not eid:
                continue
            out.append({
                "id": eid,
                "type": str(ent.get("type", "moving_object")),
                "label": str(ent.get("label", eid)),
                "properties": {k: v for k, v in ent.items() if k not in ("id", "type", "label")},
            })
        return out

    def _spec_pipeline(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for i, step in enumerate(self.steps):
            vs = step.visual_state if isinstance(step.visual_state, VisualState) else VisualState()
            cp = step.checkpoint if isinstance(step.checkpoint, Checkpoint) else None
            formula = ""
            eval_expr = ""
            result_unit = ""
            if cp:
                formula = str(cp.expected_expression or "")
                eval_expr = str(cp.expected_expression or "")
                result_unit = str(getattr(cp, "result_unit", "") or "")
            if not result_unit:
                for gv in self.global_variables.values():
                    if isinstance(gv, dict) and gv.get("unit"):
                        result_unit = str(gv["unit"])
                        break
            pr = vs.progress_range if isinstance(vs.progress_range, (list, tuple)) and len(vs.progress_range) == 2 else (0.0, 1.0)
            out.append({
                "step": i + 1,
                "title": str(step.step_title or step.step_id),
                "formula": formula,
                "eval": eval_expr,
                "result_unit": result_unit,
                "visual_state": {
                    "progress_range": [float(pr[0]), float(pr[1])],
                    "active_entities": [str(e) for e in vs.active_entities],
                    "action": str(vs.action or ""),
                },
            })
        return out


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
    """知识图谱节点 — 学科中立 (PRD §3.2 schema 抽象, issue #21 扩展)。"""
    id: str
    title: str
    node_type: str = "Concept"  # Concept | Theorem | Method | Misconception
    stage: str = ""
    strand: str = ""
    grade: str = ""
    semester: str = ""
    spatial: dict[str, float] = field(default_factory=dict)
    visual_type: str = ""
    formula: str = ""
    misconceptions: list[str] = field(default_factory=list)
    cognitive_level: str = ""
    description: str = ""
    curriculum_code: str = ""
    edges: dict[str, list[str]] = field(default_factory=dict)

    @property
    def visual_engine(self) -> str:
        return self.visual_type

    @visual_engine.setter
    def visual_engine(self, v: str) -> None:
        self.visual_type = v

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "title": self.title, "node_type": self.node_type,
            "stage": self.stage, "strand": self.strand, "grade": self.grade,
            "semester": self.semester,
            "spatial": self.spatial, "visual_type": self.visual_type,
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
