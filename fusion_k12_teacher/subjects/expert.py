"""学科知识库 — STEM、语言、文科等多学科教学支持。"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..ai_client import MLXClient

logger = logging.getLogger(__name__)


@dataclass
class SubjectExercise:
    """学科练习题。"""
    question: str = ""
    difficulty: str = "medium"
    subject: str = ""
    grade: str = ""
    hints: List[str] = field(default_factory=list)
    answer: str = ""
    explanation: str = ""
    topic: str = ""
    skills: List[str] = field(default_factory=list)


class SubjectExpert:
    """学科专家 — 对标 Claude K-12 Teacher 的多学科教学能力。

    支持：数学、科学、编程、语言、历史、地理等学科。
    """

    def __init__(self, mlx: Optional[MLXClient] = None):
        self.mlx = mlx or MLXClient()

    async def explain_concept(self, subject: str, grade: str, concept: str) -> Dict[str, Any]:
        """解释学科概念（分年级适配）。"""
        prompt = f"""用{grade}年级学生能理解的语言解释"{concept}"（{subject}学科）。

       返回JSON: {{"simple_explanation": "简单解释", "example": "生活例子", "visualization": "可视化建议", "common_misconceptions": ["常见误解"], "extension": "拓展知识"}}"""
        try:
            response = await self.mlx.chat([
                {"role": "system", "content": f"你是一位{grade}年级{subject}教师，用学生能理解的语言解释概念。"},
                {"role": "user", "content": prompt},
            ], temperature=0.3)
            return self._parse_json(response) or {"concept": concept}
        except Exception as e:
            return {"error": str(e)}

    async def generate_exercise(self, subject: str, grade: str, topic: str, difficulty: str = "medium") -> SubjectExercise:
        """生成学科练习题。"""
        prompt = f"""为{grade}年级{subject}学科生成一道{topic}相关的练习题，难度为{difficulty}。

        返回JSON: {{"question": "题目", "hints": ["提示1", "提示2"], "answer": "答案", "explanation": "解题思路", "skills": ["考察能力"]}}"""
        try:
            response = await self.mlx.chat([
                {"role": "system", "content": "你是一位经验丰富的学科教师，设计高质量的练习题。"},
                {"role": "user", "content": prompt},
            ], temperature=0.4)
            data = self._parse_json(response)
            if data:
                return SubjectExercise(
                    question=data.get("question", ""), difficulty=difficulty,
                    subject=subject, grade=grade, hints=data.get("hints", []),
                    answer=data.get("answer", ""), explanation=data.get("explanation", ""),
                    topic=topic, skills=data.get("skills", []),
                )
        except Exception as exc:
            logger.error(f"习题生成失败: {exc}")
            err_msg = str(exc)
        return SubjectExercise(question=f"生成失败: {err_msg}", topic=topic)

    async def stem_project(self, grade: str, topic: str, duration: str = "2课时") -> Dict[str, Any]:
        """生成STEM项目式学习方案。"""
        prompt = f"""为{grade}年级学生设计一个STEM项目式学习方案。

主题: {topic}
时长: {duration}

返回JSON: {{"title": "项目名称", "driving_question": "驱动性问题", "objectives": ["学习目标"], "materials": ["所需材料"], "procedure": ["步骤"], "expected_outcomes": ["预期成果"], "rubric": "评价标准"}}"""
        try:
            response = await self.mlx.chat([
                {"role": "system", "content": "你是一位STEM教育专家，设计跨学科的项目式学习方案。"},
                {"role": "user", "content": prompt},
            ], temperature=0.3)
            return self._parse_json(response) or {"title": topic}
        except Exception as e:
            return {"error": str(e)}

    async def language_activity(self, grade: str, language: str, skill: str, theme: str) -> Dict[str, Any]:
        """生成语言学习活动。"""
        prompt = f"""为{grade}年级{language}学习者设计一个{skill}练习活动。

主题: {theme}

返回JSON: {{"title": "活动名称", "objective": "学习目标", "materials": ["材料"], "procedure": ["步骤"], "differentiation": {{"beginner": "初级支持", "intermediate": "中级", "advanced": "高级"}} }}"""
        try:
            response = await self.mlx.chat([
                {"role": "system", "content": "你是一位语言教学专家，设计互动式语言学习活动。"},
                {"role": "user", "content": prompt},
            ], temperature=0.4)
            return self._parse_json(response) or {"title": f"{skill}练习"}
        except Exception as e:
            return {"error": str(e)}

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