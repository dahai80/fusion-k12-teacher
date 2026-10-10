"""数学苏格拉底课稿生成 — FusionSocratic DSL v3.0 (PRD §5, issue #19)。

按 5E 生成 TeachingStep[]: speech_narration + animation segment + checkpoint + visual_state。
苏格拉底式: 分步揭示, 连错 2 次降层 (B→A) + 回放前置节点 (PRD §5.3)。
数值字段经 MathSympyVerifier 校验。课稿供学生端逐页播放。
v3.0: meta.visual_type (8 基元路由) + meta.fallback_type + step.visual_state.action。
"""

from __future__ import annotations

import logging
from typing import Any

from ...._parse import parse_json
from ....ai_client import MLXClient
from ....errors import rethrow_if_fatal
from ....safety.filter import sanitize_input
from ...base import SocraticTutorBase
from ...models import (
    FALLBACK_TYPES,
    VISUAL_TYPES,
    AnimationSegment,
    Checkpoint,
    FallbackType,
    FusionSocraticDSL,
    JudgeResult,
    Landmark,
    SceneDSL,
    TeachingStep,
    VisualState,
    VisualType,
)
from ...prompts.bnup_socratic import (
    BNUP_SYSTEM_PROMPT,
    BNUP_VISUAL_ROUTING_PROMPT,
    route_visual_type,
)
from .sympy_verifier import MathSympyVerifier

logger = logging.getLogger(__name__)

_SCRIPT_PROMPT = BNUP_SYSTEM_PROMPT + "\n" + BNUP_VISUAL_ROUTING_PROMPT + "\n" + """你是 K12 数学苏格拉底课稿生成器。按 5E 教学法生成分步课稿 DSL。

课题: {topic} (年级 {grade})
知识点节点: {node_id}
前置知识: {prerequisites}
易错点: {misconceptions}
分层难度: {layer} (A基础/B进阶/C拔高)

要求:
- 严格分 3-5 步, 每步属于一个 5E 阶段 (Engage/Explore/Explain/Elaborate/Evaluate/Transfer)。
- 每步含 speech_narration (讲课词, 中文) + animation 段 (start_ratio/end_ratio 0-1) + 至少 2 个步骤带 checkpoint。
- checkpoint 不直接给答案, 用 hints 分级提示。
- 数值必须准确。
- meta.visual_type 从 8 基元选一: array_grid(计数阵列) / tape_diagram(和差倍比) / geometry_2d(平面几何) / isometric_3d(立体几何) / track_timeline(行程追及) / bucket_divider(组合隔板) / data_chart(统计图表) / flow_card(纯计算兜底)。
- meta.fallback_type 从 2 兜底选一: tape_diagram / flow_card。
- 每步 visual_state 描述该步可视化动作 (action=进入/更新/高亮/消隐, active_entities=实体id列表)。

输出 JSON:
{{
  "meta": {{"visual_type": "track_timeline", "fallback_type": "tape_diagram"}},
  "global_variables": {{"L_train": {{"label": "车长", "unit": "m", "value": 200, "is_unknown": false}}}},
  "steps": [
    {{
      "step_id": "step1", "step_title": "...", "phase": "Engage",
      "speech_narration": "...",
      "landmarks": [{{"timeOffsetMs": 0, "progressRatio": 0.0, "latexHighlightVar": "L_train"}}],
      "animation": {{"start_ratio": 0.0, "end_ratio": 0.3, "camera_focus_entity": "train_head", "highlight_entities": ["train_head"]}},
      "visual_state": {{"visual_type": "track_timeline", "action": "进入:列车从左驶入", "progress_range": [0.0, 0.3], "active_entities": ["train_head", "bridge"], "latex_state": "L_train=200"}},
      "checkpoint": {{
        "id": "cp1", "type": "multiple_choice", "prompt": "...",
        "options": [{{"id": "a", "label": "...", "is_correct": false, "feedback": "..."}}],
        "hints": ["提示1"], "on_error_action": "rewind", "difficulty_layer": "B",
        "expected_expression": "", "expected_value": 0, "tolerance": 0.01
      }}
    }}
  ]
}}

只输出 JSON。"""


class MathSocraticTutor(SocraticTutorBase):
    """数学苏格拉底课稿生成器 — 5E + checkpoint + 分层。"""

    def __init__(self, mlx: MLXClient, verifier: MathSympyVerifier, content_filter=None) -> None:
        self.mlx = mlx
        self.verifier = verifier
        self.content_filter = content_filter

    async def generate_lesson_script(
        self, topic: str, grade: str = "5",
        knowledge_node_id: str = "",
        prerequisites: list[str] | None = None,
        misconceptions: list[str] | None = None,
        layer: str = "B",
    ) -> FusionSocraticDSL:
        topic_s = sanitize_input(topic)[:200]
        pre = ", ".join(prerequisites or []) or "无"
        misc = ", ".join(misconceptions or []) or "无"
        prompt = _SCRIPT_PROMPT.format(
            topic=topic_s, grade=grade, node_id=knowledge_node_id or "未指定",
            prerequisites=pre, misconceptions=misc, layer=layer,
        )
        # issue #20 gap 2: CoT 模式下用 GBNF grammar 约束 stage-2 DSL 输出为合法 JSON
        from ...cot_pipeline import DSL_GBNF_GRAMMAR, cot_enabled
        grammar = DSL_GBNF_GRAMMAR if cot_enabled() else None
        try:
            raw = await self.mlx.chat(
                [{"role": "user", "content": prompt}],
                temperature=0.3, max_tokens=4096, grammar=grammar,
            )
        except Exception as exc:
            logger.warning("socratic_tutor: LLM 生成失败 %s", exc)
            rethrow_if_fatal(exc)
            return FusionSocraticDSL(subject="math", meta={"title": topic_s}, error=f"LLM 生成失败: {exc}")

        data = parse_json(raw)
        if not data or not isinstance(data, dict):
            # issue #20 gap 1: 尝试 <dsl> 标签提取 (CoT 模式下模型可能输出 <dsl>...</dsl>)
            from ...cot_pipeline import extract_dsl
            dsl_text = extract_dsl(raw)
            if dsl_text:
                data = parse_json(dsl_text)
                logger.info("socratic_tutor: extract_dsl 成功 (%d chars)", len(dsl_text))
        if not data or not isinstance(data, dict):
            # 小模型常见失败: 输出被截断/夹带非 JSON 前后缀 — 重试一次再降级,
            # 避免一次抖动直接打空讲稿 (上层回退兜底)
            logger.warning("socratic_tutor: 首次输出非 JSON (len=%d), 重试一次", len(raw or ""))
            try:
                raw2 = await self.mlx.chat(
                    [{"role": "user", "content": prompt + "\n\n注意: 只输出 JSON, 不要任何其他文字。"}],
                    temperature=0.2, max_tokens=4096, grammar=grammar,
                )
                data = parse_json(raw2)
                if not data or not isinstance(data, dict):
                    dsl_text2 = extract_dsl(raw2)
                    if dsl_text2:
                        data = parse_json(dsl_text2)
            except Exception as exc:
                logger.warning("socratic_tutor: 重试失败 %s", exc)
                rethrow_if_fatal(exc)
        if not data or not isinstance(data, dict):
            return FusionSocraticDSL(subject="math", meta={"title": topic_s}, error="LLM 输出非 JSON")

        dsl = self._build_dsl(data, topic_s, knowledge_node_id)
        logger.info("socratic_tutor: topic=%s steps=%d checkpoints=%d", topic_s, len(dsl.steps), sum(1 for s in dsl.steps if s.checkpoint))
        return dsl

    async def judge_checkpoint(self, checkpoint: Checkpoint, student_answer: str) -> JudgeResult:
        return self.verifier.judge_checkpoint(checkpoint, student_answer)

    def _build_dsl(self, data: dict[str, Any], title: str, node_id: str) -> FusionSocraticDSL:
        global_vars = data.get("global_variables", {})
        if not isinstance(global_vars, dict):
            global_vars = {}
        steps_raw = data.get("steps", [])
        if not isinstance(steps_raw, list):
            steps_raw = []
        meta_raw = data.get("meta", {})
        if not isinstance(meta_raw, dict):
            meta_raw = {}
        visual_type = str(meta_raw.get("visual_type", data.get("visual_type", "")))
        if visual_type and visual_type not in VISUAL_TYPES:
            logger.warning("socratic_tutor: visual_type 非法 %s -> flow_card", visual_type)
            visual_type = VisualType.FLOW_CARD.value
        if not visual_type:
            # issue #22: LLM 未指定时按题型关键词自动路由
            visual_type = route_visual_type(title)
            logger.info("socratic_tutor: auto-route visual_type=%s", visual_type)
        fallback_type = str(meta_raw.get("fallback_type", data.get("fallback_type", "")))
        if fallback_type and fallback_type not in FALLBACK_TYPES:
            fallback_type = FallbackType.TAPE_DIAGRAM.value
        if not fallback_type:
            fallback_type = FallbackType.TAPE_DIAGRAM.value
        scene_raw = data.get("scene", {})
        if not isinstance(scene_raw, dict):
            scene_raw = {}
        steps: list[TeachingStep] = []
        for i, s in enumerate(steps_raw[:8]):
            if not isinstance(s, dict):
                continue
            cp_raw = s.get("checkpoint")
            checkpoint = Checkpoint.from_dict(cp_raw) if isinstance(cp_raw, dict) else None
            anim_raw = s.get("animation", {})
            anim = AnimationSegment(
                start_ratio=float(anim_raw.get("start_ratio", 0)) if isinstance(anim_raw, dict) else 0,
                end_ratio=float(anim_raw.get("end_ratio", 1)) if isinstance(anim_raw, dict) else 1,
                camera_focus_entity=str(anim_raw.get("camera_focus_entity", "")) if isinstance(anim_raw, dict) else "",
                highlight_entities=[str(h) for h in (anim_raw.get("highlight_entities", []) if isinstance(anim_raw, dict) else [])][:6],
            )
            landmarks = [Landmark(
                time_offset_ms=int(lm.get("timeOffsetMs", 0) or 0),
                progress_ratio=float(lm.get("progressRatio", 0) or 0),
                latex_highlight_var=str(lm.get("latexHighlightVar", "")),
            ) for lm in (s.get("landmarks", []) if isinstance(s.get("landmarks"), list) else [])][:8]
            vs_raw = s.get("visual_state", {})
            if isinstance(vs_raw, dict):
                vs = VisualState.from_dict(vs_raw)
            else:
                vs = VisualState(visual_type=visual_type)
            if not vs.visual_type:
                vs.visual_type = visual_type
            steps.append(TeachingStep(
                step_id=str(s.get("step_id", f"step{i+1}")),
                step_title=str(s.get("step_title", ""))[:100],
                speech_narration=str(s.get("speech_narration", ""))[:1000],
                phase=str(s.get("phase", "")),
                landmarks=landmarks,
                animation=anim,
                checkpoint=checkpoint,
                visual_state=vs,
            ))
        meta = {"title": title, "knowledge_node_id": node_id,
                "visual_type": visual_type, "fallback_type": fallback_type}
        scene = SceneDSL(
            subject="math",
            template_type=str(scene_raw.get("template_type", "")),
            meta={k: str(v) for k, v in scene_raw.get("meta", {}).items()} if isinstance(scene_raw.get("meta"), dict) else {},
            entities=scene_raw.get("entities", []) if isinstance(scene_raw.get("entities"), list) else [],
            canvas_config=scene_raw.get("canvas_config", {}) if isinstance(scene_raw.get("canvas_config"), dict) else {},
            timeline=scene_raw.get("timeline", {}) if isinstance(scene_raw.get("timeline"), dict) else {},
            pedagogy=scene_raw.get("pedagogy", {}) if isinstance(scene_raw.get("pedagogy"), dict) else {},
        )
        logger.info("socratic_tutor: v3.0 visual_type=%s fallback=%s steps=%d", visual_type, fallback_type, len(steps))
        return FusionSocraticDSL(
            subject="math",
            meta=meta,
            global_variables={str(k): dict(v) if isinstance(v, dict) else {"value": v} for k, v in global_vars.items()},
            steps=steps,
            scene=scene,
        )
