"""学科知识库 — STEM、语言、文科等多学科教学支持。"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .._parse import parse_json
from ..ai_client import MLXClient
from ..errors import rethrow_if_fatal
from ..safety.filter import ContentFilter, sanitize_input

logger = logging.getLogger(__name__)


@dataclass
class SubjectExercise:
    """学科练习题。"""
    question: str = ""
    difficulty: str = "medium"
    subject: str = ""
    grade: str = ""
    hints: list[str] = field(default_factory=list)
    answer: str = ""
    explanation: str = ""
    topic: str = ""
    skills: list[str] = field(default_factory=list)


class SubjectExpert:
    """学科专家 — 对标 Claude K-12 Teacher 的多学科教学能力。

    支持：数学、科学、编程、语言、历史、地理等学科。
    """

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
            logger.warning("学科内容检出不当, 已过滤: %s", check.summary)
            return check.filtered_text
        return text

    def _filter_dict(self, data: dict[str, Any], grade: str) -> dict[str, Any]:
        # A6: dict 中字符串值与列表项过安全过滤, 递归不到嵌套 dict(够用)。
        out = {}
        for k, v in data.items():
            if isinstance(v, str):
                out[k] = self._filter_output(v, grade)
            elif isinstance(v, list):
                out[k] = [self._filter_output(x, grade) if isinstance(x, str) else x for x in v]
            else:
                out[k] = v
        return out

    async def explain_concept(self, subject: str, grade: str, concept: str) -> dict[str, Any]:
        """解释学科概念（分年级适配）。"""
        # ENG-2: 用户可控字段统一 sanitize, 防提示注入
        subject = sanitize_input(subject)
        grade = sanitize_input(grade, max_len=8)
        concept = sanitize_input(concept)
        prompt = f"""用{grade}年级学生能理解的语言解释"{concept}"（{subject}学科）。

       返回JSON: {{"simple_explanation": "简单解释", "example": "生活例子", "visualization": "可视化建议", "common_misconceptions": ["常见误解"], "extension": "拓展知识"}}"""
        try:
            response = await self.mlx.chat([
                {"role": "system", "content": f"你是一位{grade}年级{subject}教师，用学生能理解的语言解释概念。"},
                {"role": "user", "content": prompt},
            ], temperature=0.3)
            data = self._parse_json(response)
            if isinstance(data, dict):
                # A6: 概念解释直达学生, 全字段过安全过滤
                return self._filter_dict(data, grade)
            return {"concept": concept}
        except Exception as e:
            rethrow_if_fatal(e)
            return {"error": str(e)}

    async def generate_exercise(self, subject: str, grade: str, topic: str, difficulty: str = "medium") -> SubjectExercise:
        """生成学科练习题。"""
        # ENG-2: 用户可控字段统一 sanitize
        subject = sanitize_input(subject)
        grade = sanitize_input(grade, max_len=8)
        topic = sanitize_input(topic)
        prompt = f"""为{grade}年级{subject}学科生成一道{topic}相关的练习题，难度为{difficulty}。

        返回JSON: {{"question": "题目", "hints": ["提示1", "提示2"], "answer": "答案", "explanation": "解题思路", "skills": ["考察能力"]}}"""
        # ENG-1: err_msg 预定义, 避免 _parse_json 返回 None 时 UnboundLocalError
        err_msg = "解析失败"
        try:
            response = await self.mlx.chat([
                {"role": "system", "content": "你是一位经验丰富的学科教师，设计高质量的练习题。"},
                {"role": "user", "content": prompt},
            ], temperature=0.4)
            data = self._parse_json(response)
            if data:
                # A6: 题目/提示/答案/解析直达学生, 全字段过安全过滤
                return SubjectExercise(
                    question=self._filter_output(data.get("question", ""), grade),
                    difficulty=difficulty,
                    subject=subject, grade=grade,
                    hints=[self._filter_output(h, grade) for h in data.get("hints", [])],
                    answer=self._filter_output(data.get("answer", ""), grade),
                    explanation=self._filter_output(data.get("explanation", ""), grade),
                    topic=topic, skills=data.get("skills", []),
                )
        except Exception as exc:
            logger.error(f"习题生成失败: {exc}")
            rethrow_if_fatal(exc)
            err_msg = str(exc)
        return SubjectExercise(question=f"生成失败: {err_msg}", topic=topic)

    async def stem_project(self, grade: str, topic: str, duration: str = "2课时") -> dict[str, Any]:
        """生成STEM项目式学习方案。"""
        # ENG-2: 用户可控字段统一 sanitize
        grade = sanitize_input(grade, max_len=8)
        topic = sanitize_input(topic)
        prompt = f"""为{grade}年级学生设计一个STEM项目式学习方案。

主题: {topic}
时长: {duration}

返回JSON: {{"title": "项目名称", "driving_question": "驱动性问题", "objectives": ["学习目标"], "materials": ["所需材料"], "procedure": ["步骤"], "expected_outcomes": ["预期成果"], "rubric": "评价标准"}}"""
        try:
            response = await self.mlx.chat([
                {"role": "system", "content": "你是一位STEM教育专家，设计跨学科的项目式学习方案。"},
                {"role": "user", "content": prompt},
            ], temperature=0.3)
            data = self._parse_json(response)
            if isinstance(data, dict):
                # A6: STEM 方案文本与列表过安全过滤
                return self._filter_dict(data, grade)
            return {"title": topic}
        except Exception as e:
            rethrow_if_fatal(e)
            return {"error": str(e)}

    async def language_activity(self, grade: str, language: str, skill: str, theme: str) -> dict[str, Any]:
        """生成语言学习活动。"""
        # ENG-2: 用户可控字段统一 sanitize
        grade = sanitize_input(grade, max_len=8)
        language = sanitize_input(language, max_len=20)
        skill = sanitize_input(skill, max_len=20)
        theme = sanitize_input(theme)
        prompt = f"""为{grade}年级{language}学习者设计一个{skill}练习活动。

主题: {theme}

返回JSON: {{"title": "活动名称", "objective": "学习目标", "materials": ["材料"], "procedure": ["步骤"], "differentiation": {{"beginner": "初级支持", "intermediate": "中级", "advanced": "高级"}} }}"""
        try:
            response = await self.mlx.chat([
                {"role": "system", "content": "你是一位语言教学专家，设计互动式语言学习活动。"},
                {"role": "user", "content": prompt},
            ], temperature=0.4)
            data = self._parse_json(response)
            if isinstance(data, dict):
                # A6: 语言活动文本与列表过安全过滤
                return self._filter_dict(data, grade)
            return {"title": f"{skill}练习"}
        except Exception as e:
            rethrow_if_fatal(e)
            return {"error": str(e)}

    def _parse_json(self, text: str) -> Any:
        # E1: 收敛至单一 _parse.parse_json (原 split-based 变体已分叉)
        return parse_json(text)