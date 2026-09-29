"""ContentInjector — 学科内容注入器。

两路:
1. 课程路 (学科注入): SubjectModule.socratic_tutor().generate_lesson_script() -> TeachingStep -> NarrationSegment
2. 课堂路: LessonScripter.generate() -> ScriptPage -> NarrationSegment
平台零学科硬编码, 只依赖 SubjectModule + SubjectRegistry。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class NarrationSegment:
    index: int
    text: str
    emotion: str = "neutral"
    title: str = ""
    phase: str = ""
    question: dict[str, Any] = field(default_factory=dict)
    checkpoint: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index, "text": self.text, "emotion": self.emotion,
            "title": self.title, "phase": self.phase, "question": self.question,
            "checkpoint": self.checkpoint,
        }


class ContentInjector:
    def __init__(
        self, subject_registry: Any | None = None,
        lesson_scripter: Any | None = None,
    ) -> None:
        self._registry = subject_registry
        self._scripter = lesson_scripter

    async def load_lesson(
        self, subject: str, topic: str, grade: str, *,
        layer: str = "B",
        knowledge_node_id: str = "",
        prerequisites: list[str] | None = None,
        misconceptions: list[str] | None = None,
        lesson_plan: dict[str, Any] | None = None,
    ) -> list[NarrationSegment]:
        if self._registry is not None:
            try:
                return await self._load_from_course(subject, topic, grade, layer, knowledge_node_id, prerequisites, misconceptions)
            except Exception as exc:
                logger.warning("content: 课程路加载失败 %s, 回退课堂路", exc)
        if self._scripter is not None:
            return await self._load_from_classroom(subject, topic, grade, lesson_plan or {})
        logger.error("content: 无可用内容源 (registry/scripter 均 None)")
        return []

    async def _load_from_course(
        self, subject: str, topic: str, grade: str, layer: str,
        knowledge_node_id: str, prerequisites: list[str] | None, misconceptions: list[str] | None,
    ) -> list[NarrationSegment]:
        mod = self._registry.get(subject)
        tutor = mod.socratic_tutor() if mod.has_socratic_tutor else None
        if tutor is None:
            logger.warning("content: 学科 %s 无 socratic_tutor", subject)
            return []
        dsl = await tutor.generate_lesson_script(
            topic=topic, grade=grade, knowledge_node_id=knowledge_node_id,
            prerequisites=prerequisites, misconceptions=misconceptions, layer=layer,
        )
        segs: list[NarrationSegment] = []
        for i, step in enumerate(dsl.steps):
            cp = step.checkpoint.to_dict() if step.checkpoint else None
            segs.append(NarrationSegment(
                index=i, text=step.speech_narration, title=step.step_title,
                phase=step.phase, checkpoint=cp,
            ))
        logger.info("content: 课程路 subject=%s topic=%s 段数=%d", subject, topic, len(segs))
        return segs

    async def _load_from_classroom(
        self, subject: str, topic: str, grade: str, lesson_plan: dict[str, Any],
    ) -> list[NarrationSegment]:
        # 优先复用已生成 script (pack 里有), 跳过 LLM 重生成 — 省一次推理 + 避长 prompt 超时
        pre_pages = lesson_plan.get("script_pages") if lesson_plan else None
        if pre_pages:
            segs = []
            for i, p in enumerate(pre_pages):
                segs.append(NarrationSegment(
                    index=p.get("page_index", i), text=str(p.get("narration", "")),
                    emotion=p.get("emotion_tag", "neutral"), title=str(p.get("title", "")),
                    question=p.get("question_point", {}),
                ))
            logger.info("content: 课堂路(复用script) subject=%s topic=%s 段数=%d", subject, topic, len(segs))
            return segs
        script = await self._scripter.generate(subject, grade, topic, lesson_plan)
        segs: list[NarrationSegment] = []
        for page in script.pages:
            segs.append(NarrationSegment(
                index=page.page_index, text=page.narration, emotion=page.emotion_tag,
                title=page.title, question=page.question_point,
            ))
        logger.info("content: 课堂路 subject=%s topic=%s 段数=%d", subject, topic, len(segs))
        return segs

    def build_course_context(
        self, subject: str, topic: str, grade: str,
        prerequisites: list[str] | None = None, misconceptions: list[str] | None = None,
    ) -> str:
        lines = [f"学科: {subject}", "主题: " + topic, "年级: " + str(grade)]
        if prerequisites:
            lines.append("前置知识: " + ", ".join(prerequisites))
        if misconceptions:
            lines.append("常见误区: " + ", ".join(misconceptions))
        return "\n".join(lines)
