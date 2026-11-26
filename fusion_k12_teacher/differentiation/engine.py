from __future__ import annotations

import asyncio
import logging
from typing import Any

from .._parse import parse_json
from ..ai_client import MLXClient
from ..errors import rethrow_if_fatal
from ..safety.filter import ContentFilter, sanitize_input
from ..standards.aligner import StandardsAligner
from ..standards.query import StandardsQuery
from .level_config import LEVEL_CONFIGS
from .models import DifferentiatedContent, GroupTask, LayerContent

logger = logging.getLogger(__name__)

# ENG-17: tiered content goes straight to students — text/lists bounded + passed through ContentFilter
_MAX_STR = 5000
_MAX_LIST = 50


def _bound_str(val: Any) -> str:
    s = str(val) if val is not None else ""
    return s[:_MAX_STR]


def _bound_str_list(val: Any) -> list[str]:
    if not isinstance(val, list):
        return []
    return [_bound_str(x) for x in val[:_MAX_LIST]]


def _bound_exercises(val: Any, grade: str = "", filter_fn=None) -> list[Any]:
    # P1-6: tiered exercise items (question/answer/hint) go straight to students — must pass the safety filter.
    # filter_fn = engine._filter_output(text, grade); on hit, replaces with the mask.
    if not isinstance(val, list):
        return []
    _filter_keys = ("question", "answer", "hint", "explanation", "options")
    out = []
    for ex in val[:_MAX_LIST]:
        if not isinstance(ex, dict):
            continue
        item = {}
        for k, v in ex.items():
            if isinstance(v, str):
                bounded = v[:_MAX_STR]
                if filter_fn and k in _filter_keys:
                    bounded = filter_fn(bounded, grade)
                item[k] = bounded
            elif isinstance(v, list) and filter_fn and k in _filter_keys:
                item[k] = [
                    filter_fn(x[:_MAX_STR], grade) if isinstance(x, str) else x
                    for x in v[:_MAX_LIST]
                ]
            else:
                item[k] = v
        out.append(item)
    return out


def _sgt(subject: str, grade: str, topic: str) -> tuple[str, str, str]:
    return (
        sanitize_input(subject, 20),
        sanitize_input(grade, 4),
        sanitize_input(topic),
    )


class DifferentiationEngine:
    """Differentiated instruction engine — three-tier differentiated content generation."""

    def __init__(
        self,
        mlx: MLXClient | None = None,
        standards_query: StandardsQuery | None = None,
        content_filter: ContentFilter | None = None,
        aligner: StandardsAligner | None = None,
    ):
        self.mlx = mlx or MLXClient()
        # E9: aligner is injectable — constructing it directly coupled the engine to the concrete aligner,
        # making it impossible to test the engine in isolation with a fake aligner; swapping the alignment strategy required engine source changes.
        self._aligner = aligner or StandardsAligner(standards_query)
        self._filter = content_filter or ContentFilter()

    def _filter_output(self, text: str, grade: str) -> str:
        """ENG-17: tiered text passes safety.check_output; on hit, replaced with the mask and a warning is logged."""
        if not isinstance(text, str) or not text:
            return text
        check = self._filter.check_output(text, grade)
        if not check.is_safe:
            logger.warning("Inappropriate tiered content detected, filtered: %s", check.summary)
            return check.filtered_text
        return text

    @staticmethod
    def _set_layer(result: DifferentiatedContent, lvl: str, content: LayerContent) -> None:
        """E3: write into result.layers[lvl] — dict storage, so adding tiers requires no dataclass change.

        ENG-23 guard: tier name must exist in LEVEL_CONFIGS, otherwise skip to avoid writing a ghost tier.
        """
        if lvl not in LEVEL_CONFIGS:
            logger.warning("Tier %s not in LEVEL_CONFIGS, skipping assignment (config may have been renamed)", lvl)
            return
        result.layers[lvl] = content

    async def generate_differentiated_lesson(
        self,
        subject: str,
        grade: str,
        topic: str,
        duration: int = 45,
    ) -> DifferentiatedContent:
        """Generate a three-tier differentiated lesson."""
        subject_s, grade_s, topic_s = _sgt(subject, grade, topic)
        alignment = self._aligner.align(subject_s, grade_s, topic_s)
        standards_context = self._aligner.build_prompt_context(alignment)

        result = DifferentiatedContent(
            topic=topic_s, grade=grade_s, subject=subject_s,
            standards_aligned=alignment.curriculum_codes,
        )

        # E2: levels come from the single source LEVEL_CONFIGS.keys(), no more hardcoding in three places;
        # adding a tier only touches level_config.py, avoiding a missed spot silently dropping that tier.
        levels = list(LEVEL_CONFIGS.keys())
        layer_coros = [
            self._generate_layer(
                subject_s, grade_s, topic_s, lvl, duration, standards_context
            )
            for lvl in levels
        ]
        group_coro = self._generate_group_tasks(subject_s, grade_s, topic_s, duration, standards_context)
        layer_results, group_tasks = await asyncio.gather(
            asyncio.gather(*layer_coros, return_exceptions=True),
            group_coro,
            return_exceptions=True,
        )

        for lvl, lr in zip(levels, layer_results):
            if isinstance(lr, Exception):
                # P1-7: NonDegradableError (401/403/5xx) must not be swallowed by gather into an empty tier — rethrow to surface it.
                rethrow_if_fatal(lr)
                logger.error(f"Differentiated lesson generation failed [{lvl}]: {lr}")
                # R12: record the failed tier in layer_errors, no more silently degrading to an empty tier the teacher cannot see.
                result.layer_errors[lvl] = str(lr)
                self._set_layer(result, lvl, LayerContent())
            else:
                self._set_layer(result, lvl, lr)

        if isinstance(group_tasks, Exception):
            rethrow_if_fatal(group_tasks)  # P1-7
            logger.error(f"Group task generation failed: {group_tasks}")
            result.group_tasks = []
        else:
            result.group_tasks = group_tasks

        return result

    async def generate_differentiated_quiz(
        self,
        subject: str,
        grade: str,
        topic: str,
        num_questions: int = 10,
    ) -> DifferentiatedContent:
        """Generate a three-tier differentiated quiz."""
        subject_s, grade_s, topic_s = _sgt(subject, grade, topic)
        alignment = self._aligner.align(subject_s, grade_s, topic_s)
        standards_context = self._aligner.build_prompt_context(alignment)

        result = DifferentiatedContent(
            topic=topic_s, grade=grade_s, subject=subject_s,
            standards_aligned=alignment.curriculum_codes,
        )

        # E2: levels from the single source LEVEL_CONFIGS.keys()
        levels = list(LEVEL_CONFIGS.keys())
        quiz_coros = [
            self._generate_quiz_layer(
                subject_s, grade_s, topic_s, lvl, num_questions, standards_context
            )
            for lvl in levels
        ]
        quiz_results = await asyncio.gather(*quiz_coros, return_exceptions=True)
        for lvl, qr in zip(levels, quiz_results):
            if isinstance(qr, Exception):
                rethrow_if_fatal(qr)  # P1-7
                logger.error(f"Differentiated quiz generation failed [{lvl}]: {qr}")
                # R12: record the failed tier in layer_errors to surface it
                result.layer_errors[lvl] = str(qr)
                self._set_layer(result, lvl, LayerContent())
            else:
                self._set_layer(result, lvl, qr)

        return result

    async def generate_differentiated_worksheet(
        self,
        subject: str,
        grade: str,
        topic: str,
        num_questions: int = 8,
    ) -> DifferentiatedContent:
        """Generate a three-tier differentiated worksheet."""
        subject_s, grade_s, topic_s = _sgt(subject, grade, topic)
        alignment = self._aligner.align(subject_s, grade_s, topic_s)
        standards_context = self._aligner.build_prompt_context(alignment)

        result = DifferentiatedContent(
            topic=topic_s, grade=grade_s, subject=subject_s,
            standards_aligned=alignment.curriculum_codes,
        )

        # E2: levels from the single source LEVEL_CONFIGS.keys()
        levels = list(LEVEL_CONFIGS.keys())
        ws_coros = [
            self._generate_worksheet_layer(
                subject_s, grade_s, topic_s, lvl, num_questions, standards_context
            )
            for lvl in levels
        ]
        ws_results = await asyncio.gather(*ws_coros, return_exceptions=True)
        for lvl, wr in zip(levels, ws_results):
            if isinstance(wr, Exception):
                rethrow_if_fatal(wr)  # P1-7
                logger.error(f"Differentiated worksheet generation failed [{lvl}]: {wr}")
                # R12: record the failed tier in layer_errors to surface it
                result.layer_errors[lvl] = str(wr)
                self._set_layer(result, lvl, LayerContent())
            else:
                self._set_layer(result, lvl, wr)

        return result

    async def _generate_worksheet_layer(
        self,
        subject: str,
        grade: str,
        topic: str,
        level: str,
        num_questions: int,
        standards_context: str,
    ) -> LayerContent:
        """Generate a single-tier worksheet."""
        config = LEVEL_CONFIGS.get(level, LEVEL_CONFIGS["standard"])
        # i18n: user-facing
        prompt = f"""为{grade}年级{subject}课程中"{topic}"设计练习工作纸。

当前层级: {config['label']}
要求: {config['prompt_modifier']}
练习题数量: {num_questions}
提示密度: {config['hint_density']}

{standards_context}

返回JSON格式：
{{
    "explanation": "工作纸说明",
    "exercises": [{{"question": "题目", "answer": "答案", "hint": "提示", "type": "填空/选择/解答", "difficulty": "easy/medium/hard"}}],
    "hints": ["通用提示1", "通用提示2"],
    "extension": "拓展练习（如有）"
}}"""

        response = await self.mlx.chat([
            # i18n: user-facing
            {"role": "system", "content": f"你是一位专业K-12教师，为{config['label']}设计适合的练习工作纸。"},
            {"role": "user", "content": prompt},
        ], temperature=0.3)

        data = self._parse_json(response)
        if data:
            return LayerContent(
                explanation=self._filter_output(_bound_str(data.get("explanation", "")), grade),
                exercises=_bound_exercises(data.get("exercises", []), grade, self._filter_output),
                hints=[self._filter_output(s, grade) for s in _bound_str_list(data.get("hints", []))],
                extension=self._filter_output(_bound_str(data.get("extension", "")), grade),
            )
        return LayerContent()

    async def _generate_layer(
        self,
        subject: str,
        grade: str,
        topic: str,
        level: str,
        duration: int,
        standards_context: str,
    ) -> LayerContent:
        """Generate single-tier content."""
        config = LEVEL_CONFIGS.get(level, LEVEL_CONFIGS["standard"])
        # i18n: user-facing
        prompt = f"""你是一位经验丰富的K-12教师，正在为{grade}年级{subject}课程中"{topic}"主题设计教学材料。

当前层级: {config['label']}
要求: {config['prompt_modifier']}
练习题数量: {config['exercise_count']}
提示密度: {config['hint_density']}
是否包含拓展: {"是" if config['extension'] else "否"}

{standards_context}

请返回JSON格式：
{{
    "explanation": "概念讲解内容",
    "examples": ["例题1", "例题2"],
    "exercises": [{{"question": "题目", "answer": "答案", "hint": "提示", "difficulty": "easy/medium/hard"}}],
    "hints": ["提示1", "提示2"],
    "extension": "拓展内容（如有）"
}}"""

        response = await self.mlx.chat([
            # i18n: user-facing
            {"role": "system", "content": f"你是一位专业K-12教师，擅长为{config['label']}设计差异化教学材料。"},
            {"role": "user", "content": prompt},
        ], temperature=0.3)

        data = self._parse_json(response)
        if data:
            return LayerContent(
                explanation=self._filter_output(_bound_str(data.get("explanation", "")), grade),
                examples=[self._filter_output(s, grade) for s in _bound_str_list(data.get("examples", []))],
                exercises=_bound_exercises(data.get("exercises", []), grade, self._filter_output),
                hints=[self._filter_output(s, grade) for s in _bound_str_list(data.get("hints", []))],
                extension=self._filter_output(_bound_str(data.get("extension", "")), grade),
            )
        return LayerContent()

    async def _generate_quiz_layer(
        self,
        subject: str,
        grade: str,
        topic: str,
        level: str,
        num_questions: int,
        standards_context: str,
    ) -> LayerContent:
        """Generate a single-tier quiz."""
        config = LEVEL_CONFIGS.get(level, LEVEL_CONFIGS["standard"])
        # i18n: user-facing
        prompt = f"""为{grade}年级{subject}课程中"{topic}"生成测验题。

当前层级: {config['label']}
要求: {config['prompt_modifier']}
题目数量: {num_questions}

{standards_context}

返回JSON格式，每道题包含：question, type(选择/填空/解答), options(选择题), answer, hint, points, difficulty"""

        response = await self.mlx.chat([
            # i18n: user-facing
            {"role": "system", "content": f"你是一位专业K-12教师，为{config['label']}生成适合的测验题目。"},
            {"role": "user", "content": prompt},
        ], temperature=0.3)

        questions = self._parse_json(response)
        if isinstance(questions, list):
            return LayerContent(
                # i18n: user-facing
                explanation=f"{config['label']}测验",
                exercises=_bound_exercises(questions, grade, self._filter_output),
            )
        return LayerContent()

    async def _generate_group_tasks(
        self,
        subject: str,
        grade: str,
        topic: str,
        duration: int,
        standards_context: str = "",
    ) -> list[GroupTask]:
        """Generate group classroom task sheets."""
        # A7: receive and inject standards_context — group tasks align with the curriculum, not decoupled from it.
        # i18n: user-facing
        prompt = f"""为{grade}年级{subject}课程"{topic}"设计三组分层课堂任务：

A组(基础): 面向学困生，任务简单，重在巩固基础
B组(标准): 面向中等生，任务适中，重在理解应用
C组(挑战): 面向优等生，任务有挑战，重在拓展探究

总时长: {duration}分钟

{standards_context}

返回JSON格式：
[
    {{"group_name": "A组(基础)", "task_description": "任务描述", "expected_output": "预期成果", "time_allocation": "时间"}},
    {{"group_name": "B组(标准)", "task_description": "...", "expected_output": "...", "time_allocation": "..."}},
    {{"group_name": "C组(挑战)", "task_description": "...", "expected_output": "...", "time_allocation": "..."}}
]"""

        try:
            response = await self.mlx.chat([
                # i18n: user-facing
                {"role": "system", "content": "你是一位专业K-12教师，擅长设计分层分组课堂活动。"},
                {"role": "user", "content": prompt},
            ], temperature=0.3)
        except Exception as e:
            logger.error(f"Group task LLM call failed: {e}")
            rethrow_if_fatal(e)
            return []

        data = self._parse_json(response)
        if isinstance(data, list):
            tasks = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                tasks.append(GroupTask(
                    group_name=_bound_str(item.get("group_name", ""))[:100],
                    task_description=self._filter_output(_bound_str(item.get("task_description", "")), grade),
                    expected_output=self._filter_output(_bound_str(item.get("expected_output", "")), grade),
                    time_allocation=_bound_str(item.get("time_allocation", ""))[:100],
                ))
            if tasks:
                return tasks
        logger.error("Group task generation failed: LLM returned empty or unparseable output, teacher will have no group tasks")
        return []

    def _parse_json(self, text: Any) -> Any:
        # E1: consolidated into the single _parse.parse_json, no more per-engine hand-copied divergent implementations
        return parse_json(text)
