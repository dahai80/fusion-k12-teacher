from __future__ import annotations

import logging

from ._cjk import _cjk_tokens, _word_match  # E4: single CJK matching implementation, no more per-module copies
from .loader import StandardsLoader
from .models import CoverageReport, KnowledgePoint

logger = logging.getLogger(__name__)


class StandardsQuery:
    """Curriculum-standards query API — search by subject/grade/knowledge point."""

    def __init__(self, loader: StandardsLoader | None = None):
        self._loader = loader or StandardsLoader()

    def get_knowledge_points(self, subject: str, grade: str) -> list[KnowledgePoint]:
        """Get all knowledge points for a subject and grade.

        E6: goes through the loader (subject, grade) index, avoiding all_points()'s shallow
        copy of the whole dict + O(N) scan.
        """
        result = self._loader.get_knowledge_points(subject, grade)
        logger.debug(f"Standards query: {subject}/{grade} → {len(result)} knowledge points")
        return result

    def get_prerequisites(self, point_id: str) -> list[KnowledgePoint]:
        """Get the prerequisite knowledge points of a knowledge point."""
        kp = self._loader.get_point(point_id)
        if not kp:
            logger.warning(f"Knowledge point not found: {point_id}")
            return []
        result = []
        for pre_id in kp.prerequisites:
            pre = self._loader.get_point(pre_id)
            if pre:
                result.append(pre)
            else:
                logger.warning(f"Prerequisite knowledge point missing: {pre_id} (referenced by {point_id})")
        return result

    def get_progression(self, point_id: str) -> list[KnowledgePoint]:
        """Get the progression (next) knowledge points of a knowledge point."""
        kp = self._loader.get_point(point_id)
        if not kp:
            logger.warning(f"Knowledge point not found: {point_id}")
            return []
        result = []
        for next_id in kp.progression_next:
            nxt = self._loader.get_point(next_id)
            if nxt:
                result.append(nxt)
            else:
                logger.warning(f"Progression knowledge point missing: {next_id} (referenced by {point_id})")
        return result

    def find_by_topic(self, subject: str, grade: str, topic: str) -> list[KnowledgePoint]:
        """Find knowledge points by topic keyword — single characters skip fuzzy matching to avoid
        false hits (STD-4).

        STD-3: CJK has no word boundaries; `topic in description` substring matching over-hits
        ("加" matches "加权/增加/参加"); switched to topic-field substring + description whole-word
        boundary matching.
        """
        points = self.get_knowledge_points(subject, grade)
        topic_lower = topic.strip().lower()
        result = []
        # Single-character keywords only allow exact equality with a knowledge-point topic,
        # preventing "加" from matching "加权/增加"
        loose = len(topic_lower) >= 2
        for kp in points:
            kp_topic = kp.topic.lower()
            if loose:
                # STD-3: topic field allows substring (topic names are short by nature);
                # description must hit on a whole-word boundary
                if topic_lower in kp_topic or _word_match(topic_lower, kp.description.lower()):
                    result.append(kp)
            else:
                if topic_lower == kp_topic:
                    result.append(kp)
        if not result and loose:
            # STD-1: prerequisites store knowledge-point IDs which never match by topic; resolve
            # each pre_id into its KnowledgePoint and search its topic/description for the topic keyword.
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
        logger.debug(f"Topic query: {subject}/{grade}/{topic} → {len(result)} knowledge points")
        return result

    def validate_coverage(
        self, subject: str, grade: str, objectives: list[str]
    ) -> CoverageReport:
        """Validate how well teaching objectives cover the curriculum-standard knowledge points."""
        all_points = self.get_knowledge_points(subject, grade)
        if not all_points:
            logger.warning(f"Standards not found: {subject}/{grade}")
            return CoverageReport(subject=subject, grade=grade)

        # E10: precompute each objective's token set + topic substring, reuse K*O times instead
        # of re-tokenizing per point.
        # _word_match(kp_desc, obj) previously recomputed set(_cjk_tokens(obj)) each time; the
        # same obj was re-tokenized by K points.
        obj_lower = [o.lower() for o in objectives]
        obj_token_sets = [set(_cjk_tokens(o)) for o in obj_lower]
        covered = []
        missing = []
        details = []

        for kp in all_points:
            kp_topic_lower = kp.topic.lower()
            kp_desc_lower = kp.description.lower()
            # STD-4: bare CJK substring "kp.topic in obj" counts "加" as covered by "加权平均",
            # inflating coverage.
            # topic field allows substring (teaching objectives usually contain the full topic
            # name); description must hit on a whole-word boundary.
            # E10: use the precomputed obj_token_sets for bigram hits, reuse to avoid re-tokenizing.
            is_covered = False
            for obj_text, obj_set in zip(obj_lower, obj_token_sets):
                if kp_topic_lower in obj_text:
                    is_covered = True
                    break
                # description bigram whole-word hit: at least 1 kp_desc bigram falls inside the obj token set
                if any(tok in obj_set for tok in _cjk_tokens(kp_desc_lower)):
                    is_covered = True
                    break
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

        logger.info(f"Standards coverage validation: {subject}/{grade} → {covered_count}/{total} ({ratio:.1%})")
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
        """Get the list of knowledge strands for a subject and grade."""
        points = self.get_knowledge_points(subject, grade)
        return sorted({kp.strand for kp in points if kp.strand})

    def get_by_strand(self, subject: str, grade: str, strand: str) -> list[KnowledgePoint]:
        """Get knowledge points by knowledge strand."""
        points = self.get_knowledge_points(subject, grade)
        return [kp for kp in points if kp.strand == strand]

    def get_by_difficulty(self, subject: str, grade: str, level: str) -> list[KnowledgePoint]:
        """Get knowledge points by difficulty level."""
        points = self.get_knowledge_points(subject, grade)
        return [kp for kp in points if kp.difficulty_level == level]
