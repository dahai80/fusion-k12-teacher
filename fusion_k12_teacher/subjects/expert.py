# Subject knowledge base — STEM, languages, humanities and other multi-subject teaching support.

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .._parse import parse_json
from ..ai_client import MLXClient
from ..course.prompts.bnup_socratic import BNUP_SYSTEM_PROMPT, BNUP_VISUAL_ROUTING_PROMPT
from ..errors import rethrow_if_fatal
from ..safety.filter import ContentFilter, sanitize_input

logger = logging.getLogger(__name__)


# Subject exercise question.
@dataclass
class SubjectExercise:
    question: str = ""
    difficulty: str = "medium"
    subject: str = ""
    grade: str = ""
    hints: list[str] = field(default_factory=list)
    answer: str = ""
    explanation: str = ""
    topic: str = ""
    skills: list[str] = field(default_factory=list)
    # P3: add .error consistent with other engines — set on empty-output
    # degradation, route _check_engine_error can trigger 502, no longer always 200.
    error: str = ""


# Subject expert — multi-subject teaching on par with Claude K-12 Teacher.
#
#     Supports math, science, coding, languages, history, geography and more.
class SubjectExpert:

    def __init__(self, mlx: MLXClient | None = None, content_filter: ContentFilter | None = None):
        self.mlx = mlx or MLXClient()
        # A6: unified safety filtering across engines — LLM-generated content
        # passes check_output before reaching students.
        self._filter = content_filter or ContentFilter()

    def _filter_output(self, text: str, grade: str) -> str:
        # A6: replace unsafe content with a mask and warn, never let sensitive
        # content reach students directly.
        if not isinstance(text, str) or not text:
            return text
        check = self._filter.check_output(text, grade)
        if not check.is_safe:
            logger.warning("Unsafe subject content detected, filtered: %s", check.summary)
            return check.filtered_text
        return text

    def _filter_dict(self, data: dict[str, Any], grade: str) -> dict[str, Any]:
        # A6: string values and list items in the dict pass safety filtering;
        # no recursion into nested dicts (good enough).
        out = {}
        for k, v in data.items():
            if isinstance(v, str):
                out[k] = self._filter_output(v, grade)
            elif isinstance(v, list):
                out[k] = [self._filter_output(x, grade) if isinstance(x, str) else x for x in v]
            else:
                out[k] = v
        return out

    # Explain a subject concept (grade-adapted).
    async def explain_concept(self, subject: str, grade: str, concept: str) -> dict[str, Any]:
        # ENG-2: uniformly sanitize user-controlled fields, prevent prompt injection
        subject = sanitize_input(subject)
        grade = sanitize_input(grade, max_len=8)
        concept = sanitize_input(concept)
        # i18n: user-facing — LLM prompt template (product content), keep Chinese.
        prompt = f"""用{grade}年级学生能理解的语言解释"{concept}"（{subject}学科）。

       返回JSON: {{"simple_explanation": "简单解释", "example": "生活例子", "visualization": "可视化建议", "common_misconceptions": ["常见误解"], "extension": "拓展知识"}}"""
        try:
            # i18n: user-facing — LLM system prompt (product content), keep Chinese.
            response = await self.mlx.chat([
                {"role": "system", "content": (BNUP_SYSTEM_PROMPT + "\n" + BNUP_VISUAL_ROUTING_PROMPT) if subject == "数学" else f"你是一位{grade}年级{subject}教师，用学生能理解的语言解释概念。"},
                {"role": "user", "content": prompt},
            ], temperature=0.3)
            data = self._parse_json(response)
            if isinstance(data, dict):
                # A6: concept explanations reach students directly, all fields
                # pass safety filtering
                return self._filter_dict(data, grade)
            return {"concept": concept}
        except Exception as e:
            rethrow_if_fatal(e)
            return {"error": str(e)}

    # Generate a subject exercise question.
    async def generate_exercise(self, subject: str, grade: str, topic: str, difficulty: str = "medium") -> SubjectExercise:
        # ENG-2: uniformly sanitize user-controlled fields
        subject = sanitize_input(subject)
        grade = sanitize_input(grade, max_len=8)
        topic = sanitize_input(topic)
        # i18n: user-facing — LLM prompt template (product content), keep Chinese.
        prompt = f"""为{grade}年级{subject}学科生成一道{topic}相关的练习题，难度为{difficulty}。

        返回JSON: {{"question": "题目", "hints": ["提示1", "提示2"], "answer": "答案", "explanation": "解题思路", "skills": ["考察能力"]}}"""
        # ENG-1: predefine err_msg, avoid UnboundLocalError when _parse_json returns None
        err_msg = "Parse failed"
        try:
            # i18n: user-facing — LLM system prompt (product content), keep Chinese.
            response = await self.mlx.chat([
                {"role": "system", "content": (BNUP_SYSTEM_PROMPT + "\n" + BNUP_VISUAL_ROUTING_PROMPT) if subject == "数学" else "你是一位经验丰富的学科教师，设计高质量的练习题。"},
                {"role": "user", "content": prompt},
            ], temperature=0.4)
            data = self._parse_json(response)
            if data:
                # A6: question/hints/answer/explanation reach students
                # directly, all fields pass safety filtering
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
            logger.error(f"Exercise generation failed: {exc}")
            rethrow_if_fatal(exc)
            err_msg = str(exc)
        # i18n: user-facing — question text shown to students, keep Chinese.
        return SubjectExercise(question=f"生成失败: {err_msg}", topic=topic, error=err_msg)

    # i18n: user-facing — default duration label is Chinese prompt content.
    # Generate a STEM project-based learning plan.
    async def stem_project(self, grade: str, topic: str, duration: str = "2课时") -> dict[str, Any]:
        # ENG-2: uniformly sanitize user-controlled fields
        grade = sanitize_input(grade, max_len=8)
        topic = sanitize_input(topic)
        # i18n: user-facing — LLM prompt template (product content), keep Chinese.
        prompt = f"""为{grade}年级学生设计一个STEM项目式学习方案。

主题: {topic}
时长: {duration}

返回JSON: {{"title": "项目名称", "driving_question": "驱动性问题", "objectives": ["学习目标"], "materials": ["所需材料"], "procedure": ["步骤"], "expected_outcomes": ["预期成果"], "rubric": "评价标准"}}"""
        try:
            # i18n: user-facing — LLM system prompt (product content), keep Chinese.
            response = await self.mlx.chat([
                {"role": "system", "content": "你是一位STEM教育专家，设计跨学科的项目式学习方案。"},
                {"role": "user", "content": prompt},
            ], temperature=0.3)
            data = self._parse_json(response)
            if isinstance(data, dict):
                # A6: STEM plan text and lists pass safety filtering
                return self._filter_dict(data, grade)
            return {"title": topic}
        except Exception as e:
            rethrow_if_fatal(e)
            return {"error": str(e)}

    # Generate a language learning activity.
    async def language_activity(self, grade: str, language: str, skill: str, theme: str) -> dict[str, Any]:
        # ENG-2: uniformly sanitize user-controlled fields
        grade = sanitize_input(grade, max_len=8)
        language = sanitize_input(language, max_len=20)
        skill = sanitize_input(skill, max_len=20)
        theme = sanitize_input(theme)
        # i18n: user-facing — LLM prompt template (product content), keep Chinese.
        prompt = f"""为{grade}年级{language}学习者设计一个{skill}练习活动。

主题: {theme}

返回JSON: {{"title": "活动名称", "objective": "学习目标", "materials": ["材料"], "procedure": ["步骤"], "differentiation": {{"beginner": "初级支持", "intermediate": "中级", "advanced": "高级"}} }}"""
        try:
            # i18n: user-facing — LLM system prompt (product content), keep Chinese.
            response = await self.mlx.chat([
                {"role": "system", "content": "你是一位语言教学专家，设计互动式语言学习活动。"},
                {"role": "user", "content": prompt},
            ], temperature=0.4)
            data = self._parse_json(response)
            if isinstance(data, dict):
                # A6: language activity text and lists pass safety filtering
                return self._filter_dict(data, grade)
            # i18n: user-facing — activity title shown to users, keep Chinese.
            return {"title": f"{skill}练习"}
        except Exception as e:
            rethrow_if_fatal(e)
            return {"error": str(e)}

    def _parse_json(self, text: str) -> Any:
        # E1: converge on the single _parse.parse_json (the old split-based
        # variant had diverged)
        return parse_json(text)