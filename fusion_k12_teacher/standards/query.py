from __future__ import annotations

import logging

from .loader import StandardsLoader
from .models import CoverageReport, KnowledgePoint

logger = logging.getLogger(__name__)


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
        """按主题关键词查找知识点。"""
        points = self.get_knowledge_points(subject, grade)
        topic_lower = topic.lower()
        result = []
        for kp in points:
            if topic_lower in kp.topic.lower() or topic_lower in kp.description.lower():
                result.append(kp)
        if not result:
            for kp in points:
                if any(topic_lower in pre.lower() for pre in kp.prerequisites):
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
            is_covered = any(
                kp.topic.lower() in obj or kp.description.lower() in obj or obj in kp.description.lower()
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
