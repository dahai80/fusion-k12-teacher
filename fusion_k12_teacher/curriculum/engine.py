"""课程规划引擎 — 教案生成、课程设计、学习目标制定。"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from ..ai_client import MLXClient

logger = logging.getLogger(__name__)

# 课程标准和年级
GRADE_LEVELS = ["K", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"]
SUBJECTS = ["数学", "语文", "英语", "物理", "化学", "生物", "历史", "地理", "科学", "编程", "艺术", "音乐"]


@dataclass
class LessonPlan:
    """教案定义。"""
    id: str = ""
    title: str = ""
    subject: str = ""
    grade: str = ""
    duration_minutes: int = 45
    objectives: list[str] = field(default_factory=list)
    materials: list[str] = field(default_factory=list)
    procedures: list[dict[str, str]] = field(default_factory=list)
    assessment: str = ""
    homework: str = ""
    standards_aligned: list[str] = field(default_factory=list)
    differentiation: dict[str, str] = field(default_factory=dict)
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v}


@dataclass
class Quiz:
    """测验/考试定义。"""
    title: str = ""
    subject: str = ""
    grade: str = ""
    questions: list[dict[str, Any]] = field(default_factory=list)
    total_points: int = 0
    time_limit_minutes: int = 0
    answer_key: str = ""


class CurriculumEngine:
    """课程规划引擎 — 对标 Claude K-12 Teacher 的课程设计能力。

    支持：
    - 标准对齐教案生成
    - 分层教学差异化设计
    - 跨学科项目式学习
    - 单元/学期课程规划
    """

    def __init__(self, mlx: MLXClient | None = None):
        self.mlx = mlx or MLXClient()
        self._plans: dict[str, LessonPlan] = {}

    async def generate_lesson_plan(
        self,
        subject: str,
        grade: str,
        topic: str,
        duration: int = 45,
        standards: list[str] | None = None,
    ) -> LessonPlan:
        """生成标准对齐的教案。"""
        standards_str = ", ".join(standards) if standards else "Common Core"
        prompt = f"""你是一位经验丰富的K-12教师。请为以下课程生成完整教案：

学科: {subject}
年级: {grade}
主题: {topic}
课时: {duration}分钟
课程标准: {standards_str}

请返回JSON格式：
{{
    "title": "课程标题",
    "objectives": ["学习目标1", "学习目标2", "学习目标3"],
    "materials": ["所需材料1", "所需材料2"],
    "procedures": [
        {{"step": 1, "duration": "5分钟", "activity": "导入活动", "teacher_does": "教师行为", "student_does": "学生行为"}},
        {{"step": 2, "duration": "15分钟", "activity": "新知讲授", "teacher_does": "...", "student_does": "..."}}
    ],
    "assessment": "评估方式",
    "homework": "课后作业",
    "differentiation": {{
        "struggling": "对学习困难学生的支持",
        "advanced": "对学有余力学生的拓展",
        "ell": "对英语学习者的支持"
    }}
}}"""
        try:
            response = await self.mlx.chat([
                {"role": "system", "content": "你是一位专业K-12教师，生成符合课程标准的结构化教案。"},
                {"role": "user", "content": prompt},
            ], temperature=0.3)
            data = self._parse_json(response)
            if data:
                import time
                plan = LessonPlan(
                    id=f"lp_{int(time.time())}",
                    subject=subject, grade=grade, title=data.get("title", topic),
                    duration_minutes=duration, objectives=data.get("objectives", []),
                    materials=data.get("materials", []),
                    procedures=data.get("procedures", []),
                    assessment=data.get("assessment", ""),
                    homework=data.get("homework", ""),
                    standards_aligned=standards or [],
                    differentiation=data.get("differentiation", {}),
                    created_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                )
                self._plans[plan.id] = plan
                return plan
        except Exception as e:
            logger.error(f"教案生成失败: {e}")
        return LessonPlan(title=topic, subject=subject, grade=grade)

    async def generate_quiz(
        self,
        subject: str,
        grade: str,
        topic: str,
        num_questions: int = 10,
        question_types: list[str] | None = None,
    ) -> Quiz:
        """生成测验。"""
        types = question_types or ["multiple_choice", "short_answer", "true_false"]
        prompt = f"""为{grade}年级{subject}课程生成关于"{topic}"的测验：

题目数量: {num_questions}
题目类型: {', '.join(types)}

返回JSON格式，每道题包含：question, type, options(选择题), answer, points, difficulty(easy/medium/hard)"""
        try:
            response = await self.mlx.chat([
                {"role": "system", "content": "你是一位专业K-12教师，生成适合学生年龄段的测验题目。"},
                {"role": "user", "content": prompt},
            ], temperature=0.3)
            questions = self._parse_json(response)
            if isinstance(questions, list):
                return Quiz(
                    title=f"{topic}测验", subject=subject, grade=grade,
                    questions=questions,
                    total_points=sum(q.get("points", 1) for q in questions),
                    answer_key="[详见每道题目的answer字段]",
                )
        except Exception as e:
            logger.error(f"测验生成失败: {e}")
        return Quiz(title=f"{topic}测验", subject=subject, grade=grade)

    async def generate_unit_plan(self, subject: str, grade: str, unit_title: str, weeks: int = 4) -> dict[str, Any]:
        """生成单元教学计划。"""
        prompt = f"""为{grade}年级{subject}设计一个为期{weeks}周的教学单元：
单元主题: {unit_title}
请返回JSON格式，包含每周的教学主题、学习目标、主要活动和评估方式。"""
        try:
            response = await self.mlx.chat([
                {"role": "system", "content": "你是一位课程设计专家，设计完整的单元教学计划。"},
                {"role": "user", "content": prompt},
            ], temperature=0.3)
            return self._parse_json(response) or {"unit_title": unit_title}
        except Exception as e:
            logger.error(f"单元计划生成失败: {e}")
            return {"unit_title": unit_title}

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