from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from ..ai_client import MLXClient
from ..safety.filter import sanitize_input
from ..standards.aligner import StandardsAligner
from ..standards.query import StandardsQuery
from .level_config import LEVEL_CONFIGS
from .models import DifferentiatedContent, GroupTask, LayerContent

logger = logging.getLogger(__name__)


def _sgt(subject: str, grade: str, topic: str) -> tuple[str, str, str]:
    return (
        sanitize_input(subject, 20),
        sanitize_input(grade, 4),
        sanitize_input(topic),
    )


class DifferentiationEngine:
    """分层教学引擎 — 三层差异化内容生成。"""

    def __init__(
        self,
        mlx: MLXClient | None = None,
        standards_query: StandardsQuery | None = None,
    ):
        self.mlx = mlx or MLXClient()
        self._aligner = StandardsAligner(standards_query)

    async def generate_differentiated_lesson(
        self,
        subject: str,
        grade: str,
        topic: str,
        duration: int = 45,
    ) -> DifferentiatedContent:
        """生成三层分层教案。"""
        subject_s, grade_s, topic_s = _sgt(subject, grade, topic)
        alignment = self._aligner.align(subject_s, grade_s, topic_s)
        standards_context = self._aligner.build_prompt_context(alignment)

        result = DifferentiatedContent(
            topic=topic_s, grade=grade_s, subject=subject_s,
            standards_aligned=alignment.curriculum_codes,
        )

        levels = ["struggling", "standard", "advanced"]
        layer_coros = [
            self._generate_layer(
                subject_s, grade_s, topic_s, lvl, duration, standards_context
            )
            for lvl in levels
        ]
        group_coro = self._generate_group_tasks(subject_s, grade_s, topic_s, duration)
        layer_results, group_tasks = await asyncio.gather(
            asyncio.gather(*layer_coros, return_exceptions=True),
            group_coro,
            return_exceptions=True,
        )

        for lvl, lr in zip(levels, layer_results):
            if isinstance(lr, Exception):
                logger.error(f"分层教案生成失败 [{lvl}]: {lr}")
                setattr(result, lvl, LayerContent())
            else:
                setattr(result, lvl, lr)

        if isinstance(group_tasks, Exception):
            logger.error(f"分组任务生成失败: {group_tasks}")
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
        """生成三层分层测验。"""
        subject_s, grade_s, topic_s = _sgt(subject, grade, topic)
        alignment = self._aligner.align(subject_s, grade_s, topic_s)
        standards_context = self._aligner.build_prompt_context(alignment)

        result = DifferentiatedContent(
            topic=topic_s, grade=grade_s, subject=subject_s,
            standards_aligned=alignment.curriculum_codes,
        )

        levels = ["struggling", "standard", "advanced"]
        quiz_coros = [
            self._generate_quiz_layer(
                subject_s, grade_s, topic_s, lvl, num_questions, standards_context
            )
            for lvl in levels
        ]
        quiz_results = await asyncio.gather(*quiz_coros, return_exceptions=True)
        for lvl, qr in zip(levels, quiz_results):
            if isinstance(qr, Exception):
                logger.error(f"分层测验生成失败 [{lvl}]: {qr}")
                setattr(result, lvl, LayerContent())
            else:
                setattr(result, lvl, qr)

        return result

    async def generate_differentiated_worksheet(
        self,
        subject: str,
        grade: str,
        topic: str,
        num_questions: int = 8,
    ) -> DifferentiatedContent:
        """生成三层分层工作纸。"""
        subject_s, grade_s, topic_s = _sgt(subject, grade, topic)
        alignment = self._aligner.align(subject_s, grade_s, topic_s)
        standards_context = self._aligner.build_prompt_context(alignment)

        result = DifferentiatedContent(
            topic=topic_s, grade=grade_s, subject=subject_s,
            standards_aligned=alignment.curriculum_codes,
        )

        levels = ["struggling", "standard", "advanced"]
        ws_coros = [
            self._generate_worksheet_layer(
                subject_s, grade_s, topic_s, lvl, num_questions, standards_context
            )
            for lvl in levels
        ]
        ws_results = await asyncio.gather(*ws_coros, return_exceptions=True)
        for lvl, wr in zip(levels, ws_results):
            if isinstance(wr, Exception):
                logger.error(f"分层工作纸生成失败 [{lvl}]: {wr}")
                setattr(result, lvl, LayerContent())
            else:
                setattr(result, lvl, wr)

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
        """生成单层工作纸。"""
        config = LEVEL_CONFIGS.get(level, LEVEL_CONFIGS["standard"])
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
            {"role": "system", "content": f"你是一位专业K-12教师，为{config['label']}设计适合的练习工作纸。"},
            {"role": "user", "content": prompt},
        ], temperature=0.3)

        data = self._parse_json(response)
        if data:
            return LayerContent(
                explanation=data.get("explanation", ""),
                exercises=data.get("exercises", []),
                hints=data.get("hints", []),
                extension=data.get("extension", ""),
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
        """生成单层内容。"""
        config = LEVEL_CONFIGS.get(level, LEVEL_CONFIGS["standard"])
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
            {"role": "system", "content": f"你是一位专业K-12教师，擅长为{config['label']}设计差异化教学材料。"},
            {"role": "user", "content": prompt},
        ], temperature=0.3)

        data = self._parse_json(response)
        if data:
            return LayerContent(
                explanation=data.get("explanation", ""),
                examples=data.get("examples", []),
                exercises=data.get("exercises", []),
                hints=data.get("hints", []),
                extension=data.get("extension", ""),
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
        """生成单层测验。"""
        config = LEVEL_CONFIGS.get(level, LEVEL_CONFIGS["standard"])
        prompt = f"""为{grade}年级{subject}课程中"{topic}"生成测验题。

当前层级: {config['label']}
要求: {config['prompt_modifier']}
题目数量: {num_questions}

{standards_context}

返回JSON格式，每道题包含：question, type(选择/填空/解答), options(选择题), answer, hint, points, difficulty"""

        response = await self.mlx.chat([
            {"role": "system", "content": f"你是一位专业K-12教师，为{config['label']}生成适合的测验题目。"},
            {"role": "user", "content": prompt},
        ], temperature=0.3)

        questions = self._parse_json(response)
        if isinstance(questions, list):
            return LayerContent(
                explanation=f"{config['label']}测验",
                exercises=questions,
            )
        return LayerContent()

    async def _generate_group_tasks(
        self,
        subject: str,
        grade: str,
        topic: str,
        duration: int,
    ) -> list[GroupTask]:
        """生成分组课堂任务单。"""
        prompt = f"""为{grade}年级{subject}课程"{topic}"设计三组分层课堂任务：

A组(基础): 面向学困生，任务简单，重在巩固基础
B组(标准): 面向中等生，任务适中，重在理解应用
C组(挑战): 面向优等生，任务有挑战，重在拓展探究

总时长: {duration}分钟

返回JSON格式：
[
    {{"group_name": "A组(基础)", "task_description": "任务描述", "expected_output": "预期成果", "time_allocation": "时间"}},
    {{"group_name": "B组(标准)", "task_description": "...", "expected_output": "...", "time_allocation": "..."}},
    {{"group_name": "C组(挑战)", "task_description": "...", "expected_output": "...", "time_allocation": "..."}}
]"""

        try:
            response = await self.mlx.chat([
                {"role": "system", "content": "你是一位专业K-12教师，擅长设计分层分组课堂活动。"},
                {"role": "user", "content": prompt},
            ], temperature=0.3)
        except Exception as e:
            logger.error(f"分组任务 LLM 调用失败: {e}")
            return []

        data = self._parse_json(response)
        if isinstance(data, list):
            tasks = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                tasks.append(GroupTask(
                    group_name=str(item.get("group_name", "")),
                    task_description=str(item.get("task_description", "")),
                    expected_output=str(item.get("expected_output", "")),
                    time_allocation=str(item.get("time_allocation", "")),
                ))
            if tasks:
                return tasks
        logger.error("分组任务生成失败: LLM 返回空或无法解析, 教师将无分组任务")
        return []

    def _parse_json(self, text: Any) -> Any:
        if not isinstance(text, str) or not text.strip():
            return None
        text = text.strip()
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
        if match:
            text = match.group(1).strip()
        else:
            obj_match = re.search(r"\{.*\}|\[.*\]", text, re.DOTALL)
            if obj_match:
                text = obj_match.group(0)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None
