from __future__ import annotations

import logging

from .models import AlignmentContext
from .query import StandardsQuery

logger = logging.getLogger(__name__)


class StandardsAligner:
    """课标对齐器 — 生成内容时自动注入课标上下文。"""

    def __init__(self, query: StandardsQuery | None = None):
        self._query = query or StandardsQuery()

    def align(
        self, subject: str, grade: str, topic: str
    ) -> AlignmentContext:
        """返回课标对齐上下文，注入到 engine prompt。"""
        points = self._query.find_by_topic(subject, grade, topic)

        if not points:
            logger.info(f"课标未命中: {subject}/{grade}/{topic}，尝试宽泛匹配")
            all_points = self._query.get_knowledge_points(subject, grade)
            topic_lower = topic.lower()
            topic_tokens = [t for t in topic_lower.split() if t]
            for kp in all_points:
                kp_text = (kp.topic + " " + kp.description).lower()
                if any(tok in kp_text for tok in topic_tokens) or topic_lower in kp_text:
                    points.append(kp)

        prerequisites = []
        for kp in points:
            pres = self._query.get_prerequisites(kp.id)
            if pres:
                prerequisites.append(pres)

        must_cover = [kp.id for kp in points if kp.difficulty_level == "basic"]
        optional_advanced = [kp.id for kp in points if kp.difficulty_level == "advanced"]
        curriculum_codes = [kp.curriculum_code for kp in points if kp.curriculum_code]
        suggested_objectives = [kp.description for kp in points if kp.description]

        ctx = AlignmentContext(
            knowledge_points=points,
            prerequisites=prerequisites,
            curriculum_codes=curriculum_codes,
            suggested_objectives=suggested_objectives,
            must_cover=must_cover,
            optional_advanced=optional_advanced,
        )

        logger.info(
            f"课标对齐: {subject}/{grade}/{topic} → "
            f"{len(points)} 知识点, {len(must_cover)} 必修, {len(optional_advanced)} 拓展"
        )
        return ctx

    def build_prompt_context(self, alignment: AlignmentContext) -> str:
        """将 AlignmentContext 转为可注入 prompt 的文本。"""
        if not alignment.knowledge_points:
            return ""

        lines = ["【课标对齐要求】"]

        if alignment.curriculum_codes:
            lines.append(f"课标编码: {', '.join(alignment.curriculum_codes)}")

        if alignment.suggested_objectives:
            lines.append("课标要求的学习目标:")
            for i, obj in enumerate(alignment.suggested_objectives, 1):
                lines.append(f"  {i}. {obj}")

        if alignment.must_cover:
            lines.append(f"必修知识点（必须覆盖）: {', '.join(alignment.must_cover)}")

        if alignment.optional_advanced:
            lines.append(f"拓展知识点（可选）: {', '.join(alignment.optional_advanced)}")

        if alignment.prerequisites:
            all_pre = [kp for group in alignment.prerequisites for kp in group]
            if all_pre:
                pre_topics = list({kp.topic for kp in all_pre})
                lines.append(f"前置知识: {', '.join(pre_topics)}")

        return "\n".join(lines)

    def validate_alignment(
        self, subject: str, grade: str, generated_objectives: list
    ) -> dict:
        """验证生成内容是否覆盖课标必修(basic)知识点。"""
        all_points = self._query.get_knowledge_points(subject, grade)
        must_cover = [kp for kp in all_points if kp.difficulty_level == "basic"]

        if not must_cover:
            logger.info(f"对齐验证: {subject}/{grade} 无必修知识点，视为已对齐")
            return {"aligned": True, "coverage": 1.0, "missing": []}

        covered = []
        missing = []
        obj_tokens = []
        for o in generated_objectives:
            o_str = str(o).lower()
            obj_tokens.extend([t for t in o_str.split() if t])

        for kp in must_cover:
            kp_text = (kp.topic + " " + kp.description).lower()
            kp_tokens = [t for t in kp_text.split() if t]
            if kp.topic.lower() in " ".join(obj_tokens) or any(
                tok and tok in obj_tokens for tok in kp_tokens
            ):
                covered.append(kp.id)
            else:
                missing.append(kp.id)

        total = len(must_cover)
        coverage = len(covered) / total if total > 0 else 1.0

        logger.info(f"对齐验证: 覆盖 {len(covered)}/{total} 必修知识点")
        return {
            "aligned": len(missing) == 0,
            "coverage": coverage,
            "missing": missing,
        }
