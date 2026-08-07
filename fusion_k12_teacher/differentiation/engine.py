from __future__ import annotations

import json
import logging
from typing import Any

from ..ai_client import MLXClient
from ..standards.aligner import StandardsAligner
from ..standards.query import StandardsQuery
from .level_config import LEVEL_CONFIGS
from .models import DifferentiatedContent, GroupTask, LayerContent

logger = logging.getLogger(__name__)


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
        alignment = self._aligner.align(subject, grade, topic)
        standards_context = self._aligner.build_prompt_context(alignment)

        result = DifferentiatedContent(
            topic=topic, grade=grade, subject=subject,
            standards_aligned=alignment.curriculum_codes,
        )

        for level_name in ["struggling", "standard", "advanced"]:
            try:
                layer = await self._generate_layer(
                    subject, grade, topic, level_name, duration, standards_context
                )
                setattr(result, level_name, layer)
            except Exception as e:
                logger.error(f"分层教案生成失败 [{level_name}]: {e}")
                setattr(result, level_name, LayerContent())

        try:
            result.group_tasks = await self._generate_group_tasks(
                subject, grade, topic, duration
            )
        except Exception as e:
            logger.error(f"分组任务生成失败: {e}")
            result.group_tasks = []

        return result

    async def generate_differentiated_quiz(
        self,
        subject: str,
        grade: str,
        topic: str,
        num_questions: int = 10,
    ) -> DifferentiatedContent:
        """生成三层分层测验。"""
        alignment = self._aligner.align(subject, grade, topic)
        standards_context = self._aligner.build_prompt_context(alignment)

        result = DifferentiatedContent(
            topic=topic, grade=grade, subject=topic,
            standards_aligned=alignment.curriculum_codes,
        )

        for level_name in ["struggling", "standard", "advanced"]:
            try:
                layer = await self._generate_quiz_layer(
                    subject, grade, topic, level_name, num_questions, standards_context
                )
                setattr(result, level_name, layer)
            except Exception as e:
                logger.error(f"分层测验生成失败 [{level_name}]: {e}")
                setattr(result, level_name, LayerContent())

        return result

    async def generate_differentiated_worksheet(
        self,
        subject: str,
        grade: str,
        topic: str,
        num_questions: int = 8,
    ) -> DifferentiatedContent:
        """生成三层分层工作纸。"""
        alignment = self._aligner.align(subject, grade, topic)
        standards_context = self._aligner.build_prompt_context(alignment)

        result = DifferentiatedContent(
            topic=topic, grade=grade, subject=subject,
            standards_aligned=alignment.curriculum_codes,
        )

        for level_name in ["struggling", "standard", "advanced"]:
            try:
                layer = await self._generate_worksheet_layer(
                    subject, grade, topic, level_name, num_questions, standards_context
                )
                setattr(result, level_name, layer)
            except Exception as e:
                logger.error(f"分层工作纸生成失败 [{level_name}]: {e}")
                setattr(result, level_name, LayerContent())

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

        response = await self.mlx.chat([
            {"role": "system", "content": "你是一位专业K-12教师，擅长设计分层分组课堂活动。"},
            {"role": "user", "content": prompt},
        ], temperature=0.3)

        data = self._parse_json(response)
        if isinstance(data, list):
            return [
                GroupTask(
                    group_name=item.get("group_name", ""),
                    task_description=item.get("task_description", ""),
                    expected_output=item.get("expected_output", ""),
                    time_allocation=item.get("time_allocation", ""),
                )
                for item in data
            ]
        return []

    def _parse_json(self, text: str) -> Any:
        text = text.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None
