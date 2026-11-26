from __future__ import annotations

import logging
import os

from ..safety.filter import sanitize_input
from ._cjk import _cjk_tokens, _word_match  # E4: single CJK implementation, no more per-file copies
from .models import AlignmentContext
from .query import StandardsQuery

logger = logging.getLogger(__name__)


# Curriculum standards aligner — auto-injects standards context during content generation.
class StandardsAligner:

    def __init__(self, query: StandardsQuery | None = None):
        self._query = query or StandardsQuery()
        # A7: cache AlignmentContext by (subject,grade,topic) — a single-topic lesson+quiz+worksheet
        # generation calls align() 3 times on the same triple; with unchanged standards data the
        # cache hit skips the repeated scan.
        # P3: bounded cache — the topic set is bounded in practice, but this guards against abnormal
        # input (random topics) blowing up memory; evicts oldest beyond _max_cache.
        self._cache: dict[tuple[str, str, str], AlignmentContext] = {}
        self._max_cache = int(os.environ.get("FUSION_K12_ALIGN_CACHE_MAX", "500"))

    # Returns the standards alignment context, injected into engine prompts.
    def align(
        self, subject: str, grade: str, topic: str
    ) -> AlignmentContext:
        cache_key = (subject, grade, topic)
        # A7: return directly on cache hit, skipping find_by_topic + fallback + prerequisite computation
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.debug(f"standards alignment cache hit: {subject}/{grade}/{topic}")
            return cached
        points = self._query.find_by_topic(subject, grade, topic)

        if not points:
            logger.info(f"standards miss: {subject}/{grade}/{topic}, trying broad match")
            all_points = self._query.get_knowledge_points(subject, grade)
            topic_lower = topic.lower()
            for kp in all_points:
                # A10: fallback reuses query._word_match — consistent with the find_by_topic main path,
                # so bare substring matching cannot re-introduce over-matching like "加" hitting
                # "加权/参加" (the STD-3 fix regressing in the fallback).
                # topic field substring + description whole-word hit, same strategy as find_by_topic L107.
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
            f"standards alignment: {subject}/{grade}/{topic} → "
            f"{len(points)} knowledge points, {len(must_cover)} basic, {len(optional_advanced)} advanced"
        )
        # A7: store into cache, later hits on the same triple skip recomputation
        # P3: evict the oldest entry beyond _max_cache (dict keeps insertion order, pop first item),
        # preventing random topics from blowing up memory
        if len(self._cache) >= self._max_cache and cache_key not in self._cache:
            self._cache.pop(next(iter(self._cache)), None)
        self._cache[cache_key] = ctx
        return ctx

    # Converts an AlignmentContext into text injectable into prompts.
    def build_prompt_context(self, alignment: AlignmentContext) -> str:
        if not alignment.knowledge_points:
            return ""

        # i18n: user-facing (Chinese prompt text injected into engine LLM prompts)
        # ENG-11: standards files can be tampered with; topic/description/code are sanitized before entering the prompt to prevent injection
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

    # Validates whether generated content covers the standards' basic knowledge points — CJK whole-word matching (STD-7/E5).
    def validate_alignment(
        self, subject: str, grade: str, generated_objectives: list
    ) -> dict:
        all_points = self._query.get_knowledge_points(subject, grade)
        must_cover = [kp for kp in all_points if kp.difficulty_level == "basic"]

        if not must_cover:
            logger.info(f"alignment validation: {subject}/{grade} has no basic knowledge points, treated as aligned")
            return {"aligned": True, "coverage": 1.0, "missing": []}

        covered = []
        missing = []
        # E5: match on the raw objectives text, no longer bigram-joining into an obj_blob.
        # The old implementation joined the bigram list with spaces into a blob; bigrams were
        # separated by spaces, so 3+ char CJK topics (like "加权法") never substring-matched,
        # silently under-counting basic knowledge point coverage.
        obj_texts = [str(o).lower() for o in generated_objectives]
        obj_token_sets = [set(_cjk_tokens(o)) for o in obj_texts]

        for kp in must_cover:
            kp_topic_lower = kp.topic.lower()
            kp_desc_lower = kp.description.lower()
            is_covered = False
            for obj_text, obj_set in zip(obj_texts, obj_token_sets):
                # topic matches as raw-text substring (objectives usually contain the full topic name, multi-char CJK not split by spaces)
                if kp_topic_lower and kp_topic_lower in obj_text:
                    is_covered = True
                    break
                # description matches as bigram whole words — at least 1 kp_desc bigram lands in the obj token set
                if kp_desc_lower and any(tok in obj_set for tok in _cjk_tokens(kp_desc_lower)):
                    is_covered = True
                    break
            if is_covered:
                covered.append(kp.id)
            else:
                missing.append(kp.id)

        total = len(must_cover)
        coverage = len(covered) / total if total > 0 else 1.0

        logger.info(f"alignment validation: covered {len(covered)}/{total} basic knowledge points")
        return {
            "aligned": len(missing) == 0,
            "coverage": coverage,
            "missing": missing,
        }
