# ContentInjector — subject content injector.
#
# Two routes:
# 1. Course route (subject injection): SubjectModule.socratic_tutor().generate_lesson_script() -> TeachingStep -> NarrationSegment
# 2. Classroom route: LessonScripter.generate() -> ScriptPage -> NarrationSegment
# The platform has zero subject hardcoding and depends only on SubjectModule + SubjectRegistry.

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
        mode: str = "topic",
        knowledge_node_id: str = "",
        prerequisites: list[str] | None = None,
        misconceptions: list[str] | None = None,
        lesson_plan: dict[str, Any] | None = None,
    ) -> list[NarrationSegment]:
        # mode: topic=free topic (default, legacy behavior) | course=teach per lesson plan
        # (lesson_plan.script_pages required, zero LLM) | expand=extend-by-analogy (graph context
        # + extension prompt) | qa=Q&A only (no script)
        if mode == "qa":
            logger.info("content: QA-only mode subject=%s topic=%s — no script generated", subject, topic)
            return []
        if mode == "course" and lesson_plan and lesson_plan.get("script_pages"):
            segs = []
            for i, p in enumerate(lesson_plan["script_pages"]):
                segs.append(NarrationSegment(
                    index=p.get("page_index", i), text=str(p.get("narration", "")),
                    emotion=p.get("emotion_tag", "neutral"), title=str(p.get("title", "")),
                    question=p.get("question_point", {}),
                ))
            logger.info("content: lesson-plan reuse course mode subject=%s topic=%s segments=%d", subject, topic, len(segs))
            return segs
        if self._registry is not None:
            try:
                # Extend-by-analogy: pull prerequisite nodes + common misconceptions from the knowledge
                # graph so the LLM expands around the knowledge point instead of reciting the textbook
                if mode == "expand" and not prerequisites and not misconceptions:
                    pre, misc, node_id = self._graph_context(subject, topic)
                    prerequisites = prerequisites or pre
                    misconceptions = misconceptions or misc
                    knowledge_node_id = knowledge_node_id or node_id
                    # i18n: user-facing (LLM prompt suffix, Chinese teaching product)
                    topic = f"{topic}（举一反三拓展讲法, 不照课本顺序, 用生活实例类比延伸）"
                    logger.info("content: expand mode pre=%s misc=%s node=%s", pre, misc, node_id or "-")
                segs = await self._load_from_course(subject, topic, grade, layer, knowledge_node_id, prerequisites, misconceptions)
                if segs:
                    return segs
                # Empty course-route segments (e.g. small model outputs non-JSON → steps=0) must not
                # silently return empty — fall back to the classroom route so the digital human
                # always has a script to speak (black-screen + no-audio fix)
                logger.warning("content: course route returned 0 segments subject=%s topic=%s, falling back to classroom route", subject, topic)
            except Exception as exc:
                logger.warning("content: course route load failed %s, falling back to classroom route", exc)
        if self._scripter is not None:
            return await self._load_from_classroom(subject, topic, grade, lesson_plan or {})
        logger.error("content: no available content source (both registry/scripter None)")
        return []

    async def _load_from_course(
        self, subject: str, topic: str, grade: str, layer: str,
        knowledge_node_id: str, prerequisites: list[str] | None, misconceptions: list[str] | None,
    ) -> list[NarrationSegment]:
        mod = self._registry.get(subject)
        tutor = mod.socratic_tutor() if mod.has_socratic_tutor else None
        if tutor is None:
            logger.warning("content: subject %s has no socratic_tutor", subject)
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
        logger.info("content: course route subject=%s topic=%s segments=%d", subject, topic, len(segs))
        return segs

    async def _load_from_classroom(
        self, subject: str, topic: str, grade: str, lesson_plan: dict[str, Any],
    ) -> list[NarrationSegment]:
        # Prefer reusing an already-generated script (present in the pack), skipping LLM
        # regeneration — saves one inference + avoids long-prompt timeouts
        pre_pages = lesson_plan.get("script_pages") if lesson_plan else None
        if pre_pages:
            segs = []
            for i, p in enumerate(pre_pages):
                segs.append(NarrationSegment(
                    index=p.get("page_index", i), text=str(p.get("narration", "")),
                    emotion=p.get("emotion_tag", "neutral"), title=str(p.get("title", "")),
                    question=p.get("question_point", {}),
                ))
            logger.info("content: classroom route (reused script) subject=%s topic=%s segments=%d", subject, topic, len(segs))
            return segs
        script = await self._scripter.generate(subject, grade, topic, lesson_plan)
        segs: list[NarrationSegment] = []
        for page in script.pages:
            segs.append(NarrationSegment(
                index=page.page_index, text=page.narration, emotion=page.emotion_tag,
                title=page.title, question=page.question_point,
            ))
        logger.info("content: classroom route subject=%s topic=%s segments=%d", subject, topic, len(segs))
        return segs

    # Extend-by-analogy context: find the graph node matching the topic → (prerequisite nodes, misconceptions, node_id).
    def _graph_context(self, subject: str, topic: str) -> tuple[list[str], list[str], str]:
        try:
            mod = self._registry.get(subject)
            graph = mod.knowledge_graph() if mod else None
            if graph is None:
                return [], [], ""
            nodes = graph.query() or []
            target = next((n for n in nodes
                           if topic in n.title or n.title in topic), None)
            if target is None:
                return [], [], ""
            # Prerequisites: same strand, lower grade nodes (numeric comparison — string comparison
            # would wrongly judge "10" < "2")
            def _g(v: Any) -> int:
                try:
                    return int(str(v).strip())
                except (ValueError, TypeError):
                    return -1
            prereq = [n.title for n in nodes
                      if n.strand == target.strand and _g(n.grade) >= 0
                      and _g(n.grade) < _g(target.grade)][:3]
            misc = list(target.misconceptions)[:3]
            return prereq, misc, target.id
        except Exception as exc:
            logger.warning("content: failed to fetch graph context %s", exc)
            return [], [], ""

    def build_course_context(
        self, subject: str, topic: str, grade: str,
        prerequisites: list[str] | None = None, misconceptions: list[str] | None = None,
    ) -> str:
        # i18n: user-facing (course context block fed into Chinese LLM prompts)
        lines = [f"学科: {subject}", "主题: " + topic, "年级: " + str(grade)]
        if prerequisites:
            lines.append("前置知识: " + ", ".join(prerequisites))
        if misconceptions:
            lines.append("常见误区: " + ", ".join(misconceptions))
        return "\n".join(lines)
