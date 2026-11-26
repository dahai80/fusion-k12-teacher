# Homework grading and assessment — auto grading, feedback generation, learning analytics.

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from .._parse import parse_json
from ..ai_client import MLXClient
from ..course.prompts.bnup_socratic import BNUP_SYSTEM_PROMPT
from ..errors import rethrow_if_fatal
from ..safety.filter import ContentFilter, sanitize_input

logger = logging.getLogger(__name__)

_ESSAY_MAX = 4000
# ENG-19: comments/feedback target students and parents, pass
# safety.check_output before returning
_MAX_FEEDBACK = 5000
_MAX_LIST_ITEMS = 50


def _bound_str(val: Any) -> str:
    s = str(val) if val is not None else ""
    return s[:_MAX_FEEDBACK]


def _bound_str_list(val: Any) -> list[str]:
    if not isinstance(val, list):
        return []
    return [_bound_str(x) for x in val[:_MAX_LIST_ITEMS]]


# Clamp score into [0, total], clamp total to a positive number (ENG-10/11).
def _clamp_score(score: float, total: float) -> tuple[float, float, float]:
    total = max(float(total), 1.0)
    score = max(0.0, min(float(score), total))
    percentage = score / total * 100
    return score, total, percentage


def _to_float(value: Any, default: float = 0.0) -> float:
    # ENG-6/ENG-14: safe float conversion — strip non-numeric suffixes
    # ("85 points" → 85), fall back to default on failure;
    # do not use `value or default` (it would erase a valid 0), check
    # None/empty string directly.
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return default
    # Extract the first numeric token (integer/decimal/negative sign)
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    if not m:
        logger.warning("_to_float cannot parse numeric value: %r, falling back to %s", value, default)
        return default
    return float(m.group(0))


# Grading result.
@dataclass
class GradingResult:
    score: float = 0.0
    total: float = 0.0
    percentage: float = 0.0
    feedback: str = ""
    strengths: list[str] = field(default_factory=list)
    improvements: list[str] = field(default_factory=list)
    rubric_scores: dict[str, float] = field(default_factory=dict)
    partial: bool = False
    error: str = ""


# Student report.
@dataclass
class StudentReport:
    student_name: str = ""
    subject: str = ""
    grade: str = ""
    period: str = ""
    overall_score: float = 0.0
    skills: dict[str, float] = field(default_factory=dict)
    strengths: list[str] = field(default_factory=list)
    areas_to_improve: list[str] = field(default_factory=list)
    teacher_notes: str = ""
    error: str = ""


# Assessment engine — homework grading and assessment on par with Claude K-12 Teacher.
class AssessmentEngine:

    def __init__(self, mlx: MLXClient | None = None, content_filter: ContentFilter | None = None):
        self.mlx = mlx or MLXClient()
        self._filter = content_filter or ContentFilter()

    # ENG-19: pass comments/feedback through safety.check_output, replace
    #         with mask and warn on hit.
    def _filter_output(self, text: str, grade: str) -> str:
        if not isinstance(text, str) or not text:
            return text
        check = self._filter.check_output(text, grade)
        if not check.is_safe:
            logger.warning("Unsafe comment detected, filtered: %s", check.summary)
            return check.filtered_text
        return text

    # Grade an essay / essay question.
    async def grade_essay(self, essay: str, rubric: dict[str, int] | None = None) -> GradingResult:
        # i18n: user-facing — rubric dimension names are Chinese prompt content.
        rubric_str = json.dumps(rubric, ensure_ascii=False) if rubric else '{"内容": 40, "结构": 20, "语言": 20, "创意": 20}'
        essay_raw = sanitize_input(essay, _ESSAY_MAX)
        essay_text = essay_raw[:2000]
        partial = len(essay_raw) > 2000
        if partial:
            logger.warning("Essay exceeds 2000 chars, truncated to first 2000 for grading (original %d chars), result marked partial (ENG-12)", len(essay_raw))
        # i18n: user-facing — LLM prompt template (product content), keep Chinese.
        prompt = f"""请批改以下学生作文，给出评分和详细反馈。

评分标准: {rubric_str}
学生作文: {essay_text}

返回JSON: {{"score": 总分, "total": 总分值, "rubric_scores": {{"维度": 得分}}, "feedback": "详细反馈", "strengths": ["优点1"], "improvements": ["改进建议1"]}}"""
        err_msg = ""
        try:
            # i18n: user-facing — LLM system prompt (product content), keep Chinese.
            response = await self.mlx.chat([
                {"role": "system", "content": "你是一位经验丰富的语文教师，公正、细致地批改学生作文。"},
                {"role": "user", "content": prompt},
            ], temperature=0.2)
            data = self._parse_json(response)
            if data:
                total = _to_float(data.get("total", 100), 100)
                score = _to_float(data.get("score", 0), 0)
                score, total, percentage = _clamp_score(score, total)
                return GradingResult(
                    score=score, total=total, percentage=percentage, partial=partial,
                    feedback=self._filter_output(_bound_str(data.get("feedback", "")), "3"),
                    strengths=[self._filter_output(s, "3") for s in _bound_str_list(data.get("strengths", []))],
                    improvements=[self._filter_output(s, "3") for s in _bound_str_list(data.get("improvements", []))],
                    rubric_scores=data.get("rubric_scores", {}),
                )
            err_msg = "LLM returned empty or non-JSON"
        except Exception as exc:
            logger.error(f"Grading failed: {exc}")
            rethrow_if_fatal(exc)
            err_msg = str(exc)
        # i18n: user-facing — feedback text shown to students, keep Chinese.
        return GradingResult(score=0, total=100, percentage=0.0, feedback=f"批改失败: {err_msg}", partial=partial, error=err_msg)

    # Grade a math problem.
    async def grade_math(self, problem: str, answer: str, solution: str = "") -> GradingResult:
        problem_s = sanitize_input(problem, 1000)
        answer_s = sanitize_input(answer, 1000)
        solution_s = sanitize_input(solution, 1000)
        # i18n: user-facing — LLM prompt template (product content), keep Chinese.
        prompt = f"""批改以下数学题：

题目: {problem_s}
学生答案: {answer_s}
参考答案: {solution_s}

判断是否正确，给出评分和反馈。满分10分。返回JSON: {{"score": 得分, "total": 10, "correct": true/false, "feedback": "反馈", "mistakes": ["错误分析"]}}"""
        err_msg = ""
        try:
            # i18n: user-facing — LLM system prompt (product content), keep Chinese.
            response = await self.mlx.chat([
                {"role": "system", "content": BNUP_SYSTEM_PROMPT + "\n你是一位数学老师，严格但友好地批改数学作业。满分10分。"},
                {"role": "user", "content": prompt},
            ], temperature=0.2)
            data = self._parse_json(response)
            if data:
                total = _to_float(data.get("total", 10), 10)
                score = _to_float(data.get("score", 0), 0)
                if total > 100 or total <= 0:
                    logger.warning("Abnormal math total points (total=%s), falling back to 10", total)
                    total = 10
                score, total, percentage = _clamp_score(score, total)
                return GradingResult(
                    score=score, total=total, percentage=percentage,
                    feedback=self._filter_output(_bound_str(data.get("feedback", "")), "3"),
                    improvements=[self._filter_output(s, "3") for s in _bound_str_list(data.get("mistakes", []))],
                )
            err_msg = "LLM returned empty or non-JSON"
        except Exception as exc:
            logger.error(f"Grading failed: {exc}")
            rethrow_if_fatal(exc)
            err_msg = str(exc)
        # i18n: user-facing — feedback text shown to students, keep Chinese.
        return GradingResult(score=0, total=10, percentage=0.0, feedback=f"批改失败: {err_msg}", error=err_msg)

    # Generate a term/unit learning report.
    async def generate_report(self, student: str, subject: str, grade: str, history: list[dict]) -> StudentReport:
        student_s = sanitize_input(student, 50)
        subject_s = sanitize_input(subject, 20)
        grade_s = sanitize_input(grade, 4)
        # i18n: user-facing — LLM prompt template (product content), keep Chinese.
        prompt = f"""为以下学生生成学期学习报告：

学生: {student_s}
学科: {subject_s}
年级: {grade_s}
学习记录: {json.dumps(history[:20], ensure_ascii=False)}

返回JSON: {{"overall_score": 85, "skills": {{"技能名": 掌握度(0-100)}}, "strengths": ["优势领域"], "areas_to_improve": ["待提高领域"], "teacher_notes": "教师评语"}}"""
        try:
            # i18n: user-facing — LLM system prompt (product content), keep Chinese.
            response = await self.mlx.chat([
                {"role": "system", "content": "你是一位负责任的教师，撰写客观、鼓励性的学习报告。"},
                {"role": "user", "content": prompt},
            ], temperature=0.3)
            data = self._parse_json(response)
            if data:
                overall = float(data.get("overall_score", 0) or 0)
                overall = max(0.0, min(overall, 100.0))
                return StudentReport(
                    student_name=student_s, subject=subject_s, grade=grade_s,
                    # i18n: user-facing — report period label shown to users, keep Chinese.
                    period="本学期", overall_score=overall,
                    skills=data.get("skills", {}),
                    strengths=[self._filter_output(s, grade_s) for s in _bound_str_list(data.get("strengths", []))],
                    areas_to_improve=[self._filter_output(s, grade_s) for s in _bound_str_list(data.get("areas_to_improve", []))],
                    teacher_notes=self._filter_output(_bound_str(data.get("teacher_notes", "")), grade_s),
                )
            logger.error("Report generation failed: LLM returned empty or unparseable output")
            return StudentReport(student_name=student_s, subject=subject_s, grade=grade_s, error="LLM returned empty or unparseable output")
        except Exception as e:
            logger.error(f"Report generation failed: {e}")
            rethrow_if_fatal(e)
            return StudentReport(student_name=student_s, subject=subject_s, grade=grade_s, error=str(e))

    # Generate a grading rubric.
    async def generate_rubric(self, assignment_type: str, grade: str, criteria: list[str] | None = None) -> dict[str, Any]:
        at_s = sanitize_input(assignment_type, 50)
        grade_s = sanitize_input(grade, 4)
        # i18n: user-facing — default criteria names are Chinese prompt content.
        criteria_str = ", ".join(sanitize_input(c, 50) for c in criteria) if criteria else "内容, 结构, 语言, 创意"
        # i18n: user-facing — LLM prompt template (product content), keep Chinese.
        prompt = f"""为{grade_s}年级的{at_s}作业设计评分标准。

评分维度: {criteria_str}
返回JSON格式，每项包含：维度名称、分值、4个等级(优秀/良好/合格/需改进)的描述。"""
        try:
            # i18n: user-facing — LLM system prompt (product content), keep Chinese.
            response = await self.mlx.chat([
                {"role": "system", "content": "你是一位课程设计专家，设计清晰、可操作的评分标准。"},
                {"role": "user", "content": prompt},
            ], temperature=0.3)
            data = self._parse_json(response)
            if isinstance(data, dict):
                return data
            logger.error("Rubric generation failed: LLM returned empty or unparseable output")
            return {"criteria": criteria or [], "error": "LLM returned empty or unparseable output"}
        except Exception as e:
            logger.error(f"Rubric generation failed: {e}")
            rethrow_if_fatal(e)
            return {"criteria": criteria or [], "error": str(e)}

    def _parse_json(self, text: Any) -> Any:
        # E1: converge on the single _parse.parse_json, no more per-engine
        # hand-copied divergent implementations
        return parse_json(text)