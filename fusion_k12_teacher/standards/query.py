from __future__ import annotations

import logging
import re

from .loader import StandardsLoader
from .models import CoverageReport, KnowledgePoint

logger = logging.getLogger(__name__)

_CJK_RE = re.compile(r"[一-鿿]")


def _cjk_tokens(text: str) -> list[str]:
    """CJK+拉丁混合分词 — CJK 段取 2-gram, 拉丁段按空白切。

    与 aligner._cjk_tokens 同逻辑, 按"per-module 隔离"约定本模块独立一份。
    单字 CJK chunk 回退保留原字, 不丢弃。
    """
    text = text.lower().strip()
    tokens: list[str] = []
    for chunk in text.split():
        if _CJK_RE.search(chunk):
            tokens.extend(chunk[i:i + 2] for i in range(len(chunk) - 1))
            tokens.append(chunk)
        else:
            tokens.append(chunk)
    return [t for t in tokens if t]


def _word_match(needle: str, haystack: str) -> bool:
    """CJK 整词命中 — 用 bigram token 交集替代裸子串, 避免"加法"命中"参加法学"。

    needle/haystack 均 bigram 分词; 至少 1 个 needle bigram 出现在 haystack token 集内才算命中。
    拉丁词走精确 token 相等。无 bigram(needle<2 字)时回退裸子串(已由 loose 守门)。
    """
    if not needle:
        return False
    if len(needle) < 2:
        return needle in haystack
    hay_set = set(_cjk_tokens(haystack))
    return any(tok in hay_set for tok in _cjk_tokens(needle))


class StandardsQuery:
    """课标查询 API — 按学科/年级/知识点检索。"""

    def __init__(self, loader: StandardsLoader | None = None):
        self._loader = loader or StandardsLoader()

    def get_knowledge_points(self, subject: str, grade: str) -> list[KnowledgePoint]:
        """获取某学科某年级的全部知识点。"""
        points = self._loader.all_points()
        result = []
        for kp in points.values():
            if kp.subject == subject and kp.grade == grade:
                result.append(kp)
        result.sort(key=lambda k: k.id)
        logger.debug(f"查询课标: {subject}/{grade} → {len(result)} 个知识点")
        return result

    def get_prerequisites(self, point_id: str) -> list[KnowledgePoint]:
        """获取某知识点的前置知识点。"""
        kp = self._loader.get_point(point_id)
        if not kp:
            logger.warning(f"知识点不存在: {point_id}")
            return []
        result = []
        for pre_id in kp.prerequisites:
            pre = self._loader.get_point(pre_id)
            if pre:
                result.append(pre)
            else:
                logger.warning(f"前置知识点未找到: {pre_id} (被 {point_id} 引用)")
        return result

    def get_progression(self, point_id: str) -> list[KnowledgePoint]:
        """获取某知识点的进阶知识点。"""
        kp = self._loader.get_point(point_id)
        if not kp:
            logger.warning(f"知识点不存在: {point_id}")
            return []
        result = []
        for next_id in kp.progression_next:
            nxt = self._loader.get_point(next_id)
            if nxt:
                result.append(nxt)
            else:
                logger.warning(f"进阶知识点未找到: {next_id} (被 {point_id} 引用)")
        return result

    def find_by_topic(self, subject: str, grade: str, topic: str) -> list[KnowledgePoint]:
        """按主题关键词查找知识点 — 单字不模糊匹配, 避免误命中 (STD-4)。

        STD-3: CJK 无词边界, topic in description 子串匹配会过度命中
        ("加"命中"加权/增加/参加"); 改为 topic 字段子串 + description 整词边界。
        """
        points = self.get_knowledge_points(subject, grade)
        topic_lower = topic.strip().lower()
        result = []
        # 单字关键词仅允许精确等于知识点 topic, 杜绝"加"匹配"加权/增加"
        loose = len(topic_lower) >= 2
        for kp in points:
            kp_topic = kp.topic.lower()
            if loose:
                # STD-3: topic 字段允许子串(主题名本就短); description 须整词命中边界
                if topic_lower in kp_topic or _word_match(topic_lower, kp.description.lower()):
                    result.append(kp)
            else:
                if topic_lower == kp_topic:
                    result.append(kp)
        if not result and loose:
            # STD-1: prerequisites 存的是知识点 ID, 按 topic 永不匹配; 解析每个 pre_id
            # 取其 KnowledgePoint, 在其 topic/description 中搜 topic 关键词。
            for kp in points:
                matched = False
                for pre_id in kp.prerequisites:
                    pre = self._loader.get_point(pre_id)
                    if not pre:
                        continue
                    if topic_lower in pre.topic.lower() or _word_match(topic_lower, pre.description.lower()):
                        matched = True
                        break
                if matched:
                    result.append(kp)
        logger.debug(f"主题查询: {subject}/{grade}/{topic} → {len(result)} 个知识点")
        return result

    def validate_coverage(
        self, subject: str, grade: str, objectives: list[str]
    ) -> CoverageReport:
        """验证教学目标对课标知识点的覆盖情况。"""
        all_points = self.get_knowledge_points(subject, grade)
        if not all_points:
            logger.warning(f"未找到课标: {subject}/{grade}")
            return CoverageReport(subject=subject, grade=grade)

        objectives_lower = [o.lower() for o in objectives]
        covered = []
        missing = []
        details = []

        for kp in all_points:
            kp_topic_lower = kp.topic.lower()
            kp_desc_lower = kp.description.lower()
            # STD-4: CJK 裸子串 "kp.topic in obj" 把"加"判进"加权平均", 覆盖率虚高。
            # topic 字段允许子串(教学目标常含完整主题名); description 须整词命中。
            is_covered = any(
                kp_topic_lower in obj or _word_match(kp_desc_lower, obj)
                for obj in objectives_lower
            )
            if is_covered:
                covered.append(kp.id)
            else:
                missing.append(kp.id)
            details.append({
                "id": kp.id,
                "topic": kp.topic,
                "covered": is_covered,
            })

        total = len(all_points)
        covered_count = len(covered)
        ratio = covered_count / total if total > 0 else 0.0

        logger.info(f"课标覆盖验证: {subject}/{grade} → {covered_count}/{total} ({ratio:.1%})")
        return CoverageReport(
            subject=subject,
            grade=grade,
            total_points=total,
            covered_points=covered_count,
            coverage_ratio=ratio,
            missing_points=missing,
            details=details,
        )

    def get_strands(self, subject: str, grade: str) -> list[str]:
        """获取某学科某年级的知识领域列表。"""
        points = self.get_knowledge_points(subject, grade)
        return sorted({kp.strand for kp in points if kp.strand})

    def get_by_strand(self, subject: str, grade: str, strand: str) -> list[KnowledgePoint]:
        """按知识领域获取知识点。"""
        points = self.get_knowledge_points(subject, grade)
        return [kp for kp in points if kp.strand == strand]

    def get_by_difficulty(self, subject: str, grade: str, level: str) -> list[KnowledgePoint]:
        """按难度层级获取知识点。"""
        points = self.get_knowledge_points(subject, grade)
        return [kp for kp in points if kp.difficulty_level == level]
