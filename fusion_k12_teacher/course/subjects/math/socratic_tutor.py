"""数学苏格拉底课稿生成 — FusionSocratic DSL v2.1.0 (PRD §5)。

按 5E 生成 TeachingStep[]: speech_narration + animation segment + checkpoint。
苏格拉底式: 分步揭示, 连错 2 次降层 (B→A) + 回放前置节点 (PRD §5.3)。
数值字段经 MathSympyVerifier 校验。课稿供学生端逐页播放。
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
    AnimationSegment,
    Checkpoint,
    FusionSocraticDSL,
    JudgeResult,
    Landmark,
    TeachingStep,
)
from .sympy_verifier import MathSympyVerifier

logger = logging.getLogger(__name__)

_SCRIPT_PROMPT = """你是 K12 数学苏格拉底课稿生成器。按 5E 教学法生成分步课稿 DSL。

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

输出 JSON:
{{
  "global_variables": {{"L_train": {{"label": "车长", "unit": "m", "value": 200, "is_unknown": false}}}},
  "steps": [
    {{
      "step_id": "step1", "step_title": "...", "phase": "Engage",
      "speech_narration": "...",
      "landmarks": [{{"timeOffsetMs": 0, "progressRatio": 0.0, "latexHighlightVar": "L_train"}}],
      "animation": {{"start_ratio": 0.0, "end_ratio": 0.3, "camera_focus_entity": "train_head", "highlight_entities": ["train_head"]}},
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
        try:
            raw = await self.mlx.chat([{"role": "user", "content": prompt}], temperature=0.3, max_tokens=4096)
        except Exception as exc:
            logger.warning("socratic_tutor: LLM 生成失败 %s", exc)
            rethrow_if_fatal(exc)
            return FusionSocraticDSL(subject="math", meta={"title": topic_s}, error=f"LLM 生成失败: {exc}")

        data = parse_json(raw)
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
            steps.append(TeachingStep(
                step_id=str(s.get("step_id", f"step{i+1}")),
                step_title=str(s.get("step_title", ""))[:100],
                speech_narration=str(s.get("speech_narration", ""))[:1000],
                phase=str(s.get("phase", "")),
                landmarks=landmarks,
                animation=anim,
                checkpoint=checkpoint,
            ))
        return FusionSocraticDSL(
            subject="math",
            meta={"title": title, "knowledge_node_id": node_id},
            global_variables={str(k): dict(v) if isinstance(v, dict) else {"value": v} for k, v in global_vars.items()},
            steps=steps,
        )
