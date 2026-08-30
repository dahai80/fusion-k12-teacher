"""个性化学习路径 — 自适应学习、能力诊断、推荐系统。"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from .._parse import parse_json
from ..ai_client import MLXClient
from ..errors import rethrow_if_fatal
from ..safety.filter import ContentFilter, sanitize_input

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
    error: str = ""


class PersonalizationEngine:
    """个性化学习引擎 — 对标 Claude K-12 Teacher 的差异化教学能力。"""

    def __init__(self, mlx: MLXClient | None = None, content_filter: ContentFilter | None = None):
        self.mlx = mlx or MLXClient()
        # A6: 全引擎统一安全过滤 — LLM 生成内容送学生前过 check_output。
        self._filter = content_filter or ContentFilter()

    def _filter_output(self, text: str, grade: str) -> str:
        # A6: 命中不当内容替换掩码并告警, 不让敏感内容直达学生。
        if not isinstance(text, str) or not text:
            return text
        check = self._filter.check_output(text, grade)
        if not check.is_safe:
            logger.warning("学习路径内容检出不当, 已过滤: %s", check.summary)
            return check.filtered_text
        return text

    def _filter_list(self, items: list, grade: str) -> list:
        return [self._filter_output(x, grade) if isinstance(x, str) else x for x in items]

    async def create_learning_path(self, student: str, grade: str, subject: str, goal: str) -> LearningPath:
        """创建个性化学习路径。"""
        # ENG-2: 用户可控字段统一 sanitize
        student = sanitize_input(student, max_len=50)
        grade = sanitize_input(grade, max_len=8)
        subject = sanitize_input(subject, max_len=20)
        goal = sanitize_input(goal)
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
                # A6: 学习路径文本字段过安全过滤 — 单元 title/活动/掌握标准直达学生
                units = data.get("units", [])
                if isinstance(units, list):
                    units = [
                        {k: (self._filter_output(v, grade) if isinstance(v, str)
                             else self._filter_list(v, grade) if isinstance(v, list) else v)
                         for k, v in u.items()} if isinstance(u, dict) else u
                        for u in units
                    ]
                return LearningPath(
                    student_id=student, grade=grade, subject=subject,
                    units=units,
                    estimated_duration=self._filter_output(data.get("estimated_duration", ""), grade),
                    prerequisites=self._filter_list(data.get("prerequisites", []), grade),
                    goals=self._filter_list(data.get("goals", []), grade),
                )
        except Exception as e:
            logger.error(f"学习路径生成失败: {e}")
            rethrow_if_fatal(e)
            return LearningPath(student_id=student, grade=grade, subject=subject, error=str(e))
        return LearningPath(student_id=student, grade=grade, subject=subject, error="LLM 返回空或无法解析")

    async def diagnose_skills(self, subject: str, grade: str, responses: list[dict]) -> dict[str, Any]:
        """诊断学生能力水平。"""
        # ENG-2: 用户可控字段统一 sanitize
        subject = sanitize_input(subject, max_len=20)
        grade = sanitize_input(grade, max_len=8)
        prompt = f"""基于以下学生答题情况，诊断{grade}年级{subject}能力水平：

答题记录: {json.dumps(responses[:10], ensure_ascii=False)}

返回JSON: {{"mastered_skills": ["已掌握技能"], "developing_skills": ["发展中技能"], "needs_support": ["需支持技能"], "overall_level": "整体水平(beginner/developing/proficient/advanced)", "recommendations": ["教学建议"]}}"""
        try:
            response = await self.mlx.chat([
                {"role": "system", "content": "你是一位教育评估专家，准确诊断学生的能力水平。"},
                {"role": "user", "content": prompt},
            ], temperature=0.2)
            data = self._parse_json(response)
            if isinstance(data, dict):
                # A6: 诊断建议直达学生, 字符串与列表过安全过滤
                out = {}
                for k, v in data.items():
                    if isinstance(v, str):
                        out[k] = self._filter_output(v, grade)
                    elif isinstance(v, list):
                        out[k] = self._filter_list(v, grade)
                    else:
                        out[k] = v
                return out
            return {"overall_level": "unknown"}
        except Exception as e:
            rethrow_if_fatal(e)
            return {"error": str(e)}

    async def recommend_resources(self, student: str, grade: str, subject: str, weakness: str) -> dict[str, Any]:
        """推荐个性化学习资源。"""
        # ENG-2: 用户可控字段统一 sanitize
        student = sanitize_input(student, max_len=50)
        grade = sanitize_input(grade, max_len=8)
        subject = sanitize_input(subject, max_len=20)
        weakness = sanitize_input(weakness)
        prompt = f"""为{grade}年级学生{student}推荐针对"{weakness}"的学习资源。

返回JSON: {{"resources": [{{"type": "视频/文章/练习/游戏", "title": "资源名", "description": "说明", "duration": "时长", "difficulty": "难度"}}], "practice_plan": "练习计划", "parent_tips": "家长辅导建议"}}"""
        try:
            response = await self.mlx.chat([
                {"role": "system", "content": "你是一位教育顾问，为学生推荐最适合的学习资源。"},
                {"role": "user", "content": prompt},
            ], temperature=0.3)
            data = self._parse_json(response)
            if isinstance(data, dict):
                # A6: 资源描述/练习计划/家长建议直达学生, 字符串与列表过安全过滤
                out = {}
                for k, v in data.items():
                    if isinstance(v, str):
                        out[k] = self._filter_output(v, grade)
                    elif isinstance(v, list):
                        out[k] = [
                            {kk: (self._filter_output(vv, grade) if isinstance(vv, str) else vv)
                             for kk, vv in item.items()} if isinstance(item, dict) else
                            self._filter_output(item, grade) if isinstance(item, str) else item
                            for item in v
                        ]
                    else:
                        out[k] = v
                return out
            return {"resources": []}
        except Exception as e:
            rethrow_if_fatal(e)
            return {"error": str(e)}

    def _parse_json(self, text: str) -> Any:
        # E1: 收敛至单一 _parse.parse_json (原 split-based 变体已与 regex 变体分叉)
        return parse_json(text)