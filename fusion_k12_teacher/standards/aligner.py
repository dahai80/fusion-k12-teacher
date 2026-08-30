from __future__ import annotations

import logging
import re

from ..safety.filter import sanitize_input
from .models import AlignmentContext

# A10: 复用 query._word_match (CJK bigram 整词命中), 与 find_by_topic 主路径对齐,
# 不再 fallback 裸子串。_cjk_tokens 本模块另用于 validate_alignment, 保留本地一份。
from .query import StandardsQuery, _word_match

logger = logging.getLogger(__name__)

_CJK_RE = re.compile(r"[一-鿿]")


def _cjk_tokens(text: str) -> list[str]:
    """中文 + 空格混合分词 — CJK 段取 2-gram, 拉丁段按空白切 (STD-6/7)。

    STD-2: 单字 CJK 主题产 0 token (range(0) 无 bigram, len>=2 筛掉), 导致对齐全漏;
    单字回退保留原 chunk, 避免空 token 集恒假。
    """
    text = text.lower().strip()
    tokens: list[str] = []
    for chunk in text.split():
        if _CJK_RE.search(chunk):
            tokens.extend(chunk[i:i + 2] for i in range(len(chunk) - 1))
            if len(chunk) >= 2:
                tokens.append(chunk)
            else:
                # STD-2: 单字 CJK chunk 回退保留, 不丢弃
                tokens.append(chunk)
        else:
            tokens.append(chunk)
    return [t for t in tokens if len(t) >= 1]


class StandardsAligner:
    """课标对齐器 — 生成内容时自动注入课标上下文。"""

    def __init__(self, query: StandardsQuery | None = None):
        self._query = query or StandardsQuery()
        # A7: 按 (subject,grade,topic) 缓存 AlignmentContext — 单主题 lesson+quiz+worksheet
        # 生成时 align() 对同三元组重复计算 3 次, 课标数据不变时缓存命中免重复扫描。
        self._cache: dict[tuple[str, str, str], AlignmentContext] = {}

    def align(
        self, subject: str, grade: str, topic: str
    ) -> AlignmentContext:
        """返回课标对齐上下文，注入到 engine prompt。"""
        cache_key = (subject, grade, topic)
        # A7: 命中缓存直接返回, 跳过 find_by_topic + fallback + 前置计算
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.debug(f"课标对齐缓存命中: {subject}/{grade}/{topic}")
            return cached
        points = self._query.find_by_topic(subject, grade, topic)

        if not points:
            logger.info(f"课标未命中: {subject}/{grade}/{topic}，尝试宽泛匹配")
            all_points = self._query.get_knowledge_points(subject, grade)
            topic_lower = topic.lower()
            for kp in all_points:
                # A10: fallback 复用 query._word_match — 与 find_by_topic 主路径一致,
                # 杜绝裸子串重新引入"加"命中"加权/参加"过度命中 (STD-3 修复在 fallback 回归)。
                # topic 字段子串 + description 整词命中, 与 find_by_topic L107 同策略。
                if topic_lower in kp.topic.lower() or _word_match(topic_lower, kp.description.lower()):
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
        # A7: 入缓存, 后续同三元组命中免重复计算
        self._cache[cache_key] = ctx
        return ctx

    def build_prompt_context(self, alignment: AlignmentContext) -> str:
        """将 AlignmentContext 转为可注入 prompt 的文本。"""
        if not alignment.knowledge_points:
            return ""

        # ENG-11: 课标文件可被篡改, topic/description/code 进 prompt 前脱敏防注入
        lines = ["【课标对齐要求】"]

        if alignment.curriculum_codes:
            codes = [sanitize_input(c, 50) for c in alignment.curriculum_codes]
            lines.append(f"课标编码: {', '.join(codes)}")

        if alignment.suggested_objectives:
            lines.append("课标要求的学习目标:")
            for i, obj in enumerate(alignment.suggested_objectives, 1):
                lines.append(f"  {i}. {sanitize_input(obj, 500)}")

        if alignment.must_cover:
            ids = [sanitize_input(k, 50) for k in alignment.must_cover]
            lines.append(f"必修知识点（必须覆盖）: {', '.join(ids)}")

        if alignment.optional_advanced:
            ids = [sanitize_input(k, 50) for k in alignment.optional_advanced]
            lines.append(f"拓展知识点（可选）: {', '.join(ids)}")

        if alignment.prerequisites:
            all_pre = [kp for group in alignment.prerequisites for kp in group]
            if all_pre:
                pre_topics = list({sanitize_input(kp.topic, 100) for kp in all_pre})
                lines.append(f"前置知识: {', '.join(pre_topics)}")

        return "\n".join(lines)

    def validate_alignment(
        self, subject: str, grade: str, generated_objectives: list
    ) -> dict:
        """验证生成内容是否覆盖课标必修(basic)知识点 — CJK bigram 分词 (STD-7)。"""
        all_points = self._query.get_knowledge_points(subject, grade)
        must_cover = [kp for kp in all_points if kp.difficulty_level == "basic"]

        if not must_cover:
            logger.info(f"对齐验证: {subject}/{grade} 无必修知识点，视为已对齐")
            return {"aligned": True, "coverage": 1.0, "missing": []}

        covered = []
        missing = []
        obj_tokens: list[str] = []
        for o in generated_objectives:
            obj_tokens.extend(_cjk_tokens(str(o)))
        obj_blob = " ".join(obj_tokens)

        for kp in must_cover:
            kp_topic_lower = kp.topic.lower()
            kp_tokens = _cjk_tokens(kp.topic + " " + kp.description)
            # STD-5: any(tok in obj_tokens) 是 list 精确成员, bigram 偏移 1 即漏;
            # 改 tok in obj_blob 子串命中 (obj_blob L133 已拼, token 间以空格隔开,
            # 跨 token 子串不会假拼)。topic 整词保留子串, description 走 bigram 子串。
            if kp_topic_lower in obj_blob or any(tok in obj_blob for tok in kp_tokens):
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
