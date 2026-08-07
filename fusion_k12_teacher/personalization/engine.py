"""个性化学习路径 — 自适应学习、能力诊断、推荐系统。"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from ..ai_client import MLXClient

logger = logging.getLogger(__name__)


@dataclass
class LearningPath:
    """学习路径定义。"""
    student_id: str = ""
    grade: str = ""
    subject: str = ""
    units: list[dict[str, Any]] = field(default_factory=list)
    estimated_duration: str = ""
    prerequisites: list[str] = field(default_factory=list)
    goals: list[str] = field(default_factory=list)


class PersonalizationEngine:
    """个性化学习引擎 — 对标 Claude K-12 Teacher 的差异化教学能力。"""

    def __init__(self, mlx: MLXClient | None = None):
        self.mlx = mlx or MLXClient()

    async def create_learning_path(self, student: str, grade: str, subject: str, goal: str) -> LearningPath:
        """创建个性化学习路径。"""
        prompt = f"""为{grade}年级学生{student}制定个性化{subject}学习计划。

学习目标: {goal}

返回JSON: {{"goals": ["分解目标"], "units": [{{"title": "单元名", "duration": "建议时长", "activities": ["活动"], "mastery_criteria": "掌握标准"}}], "prerequisites": ["前置知识"], "estimated_duration": "总体预计时长"}}"""
        try:
            response = await self.mlx.chat([
                {"role": "system", "content": "你是一位教育心理学家和课程设计师，为每个学生制定个性化学习路径。"},
                {"role": "user", "content": prompt},
            ], temperature=0.3)
            data = self._parse_json(response)
            if data:
                return LearningPath(
                    student_id=student, grade=grade, subject=subject,
                    units=data.get("units", []),
                    estimated_duration=data.get("estimated_duration", ""),
                    prerequisites=data.get("prerequisites", []),
                    goals=data.get("goals", []),
                )
        except Exception as e:
            logger.error(f"学习路径生成失败: {e}")
        return LearningPath(student_id=student, grade=grade, subject=subject)

    async def diagnose_skills(self, subject: str, grade: str, responses: list[dict]) -> dict[str, Any]:
        """诊断学生能力水平。"""
        prompt = f"""基于以下学生答题情况，诊断{grade}年级{subject}能力水平：

答题记录: {json.dumps(responses[:10], ensure_ascii=False)}

返回JSON: {{"mastered_skills": ["已掌握技能"], "developing_skills": ["发展中技能"], "needs_support": ["需支持技能"], "overall_level": "整体水平(beginner/developing/proficient/advanced)", "recommendations": ["教学建议"]}}"""
        try:
            response = await self.mlx.chat([
                {"role": "system", "content": "你是一位教育评估专家，准确诊断学生的能力水平。"},
                {"role": "user", "content": prompt},
            ], temperature=0.2)
            return self._parse_json(response) or {"overall_level": "unknown"}
        except Exception as e:
            return {"error": str(e)}

    async def recommend_resources(self, student: str, grade: str, subject: str, weakness: str) -> dict[str, Any]:
        """推荐个性化学习资源。"""
        prompt = f"""为{grade}年级学生{student}推荐针对"{weakness}"的学习资源。

返回JSON: {{"resources": [{{"type": "视频/文章/练习/游戏", "title": "资源名", "description": "说明", "duration": "时长", "difficulty": "难度"}}], "practice_plan": "练习计划", "parent_tips": "家长辅导建议"}}"""
        try:
            response = await self.mlx.chat([
                {"role": "system", "content": "你是一位教育顾问，为学生推荐最适合的学习资源。"},
                {"role": "user", "content": prompt},
            ], temperature=0.3)
            return self._parse_json(response) or {"resources": []}
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