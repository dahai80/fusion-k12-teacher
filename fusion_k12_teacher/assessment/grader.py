"""作业批改与评估系统 — 自动批改、反馈生成、学习分析。"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from ..ai_client import MLXClient
from ..errors import rethrow_if_fatal
from ..safety.filter import ContentFilter, sanitize_input

logger = logging.getLogger(__name__)

_ESSAY_MAX = 4000
# ENG-19: 评语/反馈面向学生家长, 过 safety.check_output 后再返
_MAX_FEEDBACK = 5000
_MAX_LIST_ITEMS = 50


def _bound_str(val: Any) -> str:
    s = str(val) if val is not None else ""
    return s[:_MAX_FEEDBACK]


def _bound_str_list(val: Any) -> list[str]:
    if not isinstance(val, list):
        return []
    return [_bound_str(x) for x in val[:_MAX_LIST_ITEMS]]


def _clamp_score(score: float, total: float) -> tuple[float, float, float]:
    """将分数钳制到 [0, total]，total 钳制到正数 (ENG-10/11)。"""
    total = max(float(total), 1.0)
    score = max(0.0, min(float(score), total))
    percentage = score / total * 100
    return score, total, percentage


def _to_float(value: Any, default: float = 0.0) -> float:
    # ENG-6/ENG-14: 安全转 float — 剥离非数字后缀("85分"→85), 失败回退 default;
    # 不用 `value or default` (会把合法 0 抹成 default), 直接判 None/空串。
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return default
    # 提取首个数值 (整数/小数/负号)
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    if not m:
        logger.warning("_to_float 无法解析数值: %r, 回退 %s", value, default)
        return default
    return float(m.group(0))


@dataclass
class GradingResult:
    """批改结果。"""
    score: float = 0.0
    total: float = 0.0
    percentage: float = 0.0
    feedback: str = ""
    strengths: list[str] = field(default_factory=list)
    improvements: list[str] = field(default_factory=list)
    rubric_scores: dict[str, float] = field(default_factory=dict)
    partial: bool = False


@dataclass
class StudentReport:
    """学生报告。"""
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


class AssessmentEngine:
    """评估引擎 — 对标 Claude K-12 Teacher 的作业批改和评估能力。"""

    def __init__(self, mlx: MLXClient | None = None, content_filter: ContentFilter | None = None):
        self.mlx = mlx or MLXClient()
        self._filter = content_filter or ContentFilter()

    def _filter_output(self, text: str, grade: str) -> str:
        """ENG-19: 评语/反馈过 safety.check_output, 命中则替换掩码并告警。"""
        if not isinstance(text, str) or not text:
            return text
        check = self._filter.check_output(text, grade)
        if not check.is_safe:
            logger.warning("评语检出不当, 已过滤: %s", check.summary)
            return check.filtered_text
        return text

    async def grade_essay(self, essay: str, rubric: dict[str, int] | None = None) -> GradingResult:
        """批改作文/论述题。"""
        rubric_str = json.dumps(rubric, ensure_ascii=False) if rubric else '{"内容": 40, "结构": 20, "语言": 20, "创意": 20}'
        essay_raw = sanitize_input(essay, _ESSAY_MAX)
        essay_text = essay_raw[:2000]
        partial = len(essay_raw) > 2000
        if partial:
            logger.warning("作文超过2000字, 已截断前2000字批改 (原文%d字), 结果标记为partial (ENG-12)", len(essay_raw))
        prompt = f"""请批改以下学生作文，给出评分和详细反馈。

评分标准: {rubric_str}
学生作文: {essay_text}

返回JSON: {{"score": 总分, "total": 总分值, "rubric_scores": {{"维度": 得分}}, "feedback": "详细反馈", "strengths": ["优点1"], "improvements": ["改进建议1"]}}"""
        err_msg = ""
        try:
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
            err_msg = "LLM返回为空或非JSON"
        except Exception as exc:
            logger.error(f"批改失败: {exc}")
            rethrow_if_fatal(exc)
            err_msg = str(exc)
        return GradingResult(score=0, total=100, percentage=0.0, feedback=f"批改失败: {err_msg}", partial=partial)

    async def grade_math(self, problem: str, answer: str, solution: str = "") -> GradingResult:
        """批改数学题。"""
        problem_s = sanitize_input(problem, 1000)
        answer_s = sanitize_input(answer, 1000)
        solution_s = sanitize_input(solution, 1000)
        prompt = f"""批改以下数学题：

题目: {problem_s}
学生答案: {answer_s}
参考答案: {solution_s}

判断是否正确，给出评分和反馈。满分10分。返回JSON: {{"score": 得分, "total": 10, "correct": true/false, "feedback": "反馈", "mistakes": ["错误分析"]}}"""
        err_msg = ""
        try:
            response = await self.mlx.chat([
                {"role": "system", "content": "你是一位数学老师，严格但友好地批改数学作业。满分10分。"},
                {"role": "user", "content": prompt},
            ], temperature=0.2)
            data = self._parse_json(response)
            if data:
                total = _to_float(data.get("total", 10), 10)
                score = _to_float(data.get("score", 0), 0)
                if total > 100 or total <= 0:
                    logger.warning("数学满分异常(total=%s), 回退到10", total)
                    total = 10
                score, total, percentage = _clamp_score(score, total)
                return GradingResult(
                    score=score, total=total, percentage=percentage,
                    feedback=self._filter_output(_bound_str(data.get("feedback", "")), "3"),
                    improvements=[self._filter_output(s, "3") for s in _bound_str_list(data.get("mistakes", []))],
                )
            err_msg = "LLM返回为空或非JSON"
        except Exception as exc:
            logger.error(f"批改失败: {exc}")
            rethrow_if_fatal(exc)
            err_msg = str(exc)
        return GradingResult(score=0, total=10, percentage=0.0, feedback=f"批改失败: {err_msg}")

    async def generate_report(self, student: str, subject: str, grade: str, history: list[dict]) -> StudentReport:
        """生成学期/单元学习报告。"""
        student_s = sanitize_input(student, 50)
        subject_s = sanitize_input(subject, 20)
        grade_s = sanitize_input(grade, 4)
        prompt = f"""为以下学生生成学期学习报告：

学生: {student_s}
学科: {subject_s}
年级: {grade_s}
学习记录: {json.dumps(history[:20], ensure_ascii=False)}

返回JSON: {{"overall_score": 85, "skills": {{"技能名": 掌握度(0-100)}}, "strengths": ["优势领域"], "areas_to_improve": ["待提高领域"], "teacher_notes": "教师评语"}}"""
        try:
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
                    period="本学期", overall_score=overall,
                    skills=data.get("skills", {}),
                    strengths=[self._filter_output(s, grade_s) for s in _bound_str_list(data.get("strengths", []))],
                    areas_to_improve=[self._filter_output(s, grade_s) for s in _bound_str_list(data.get("areas_to_improve", []))],
                    teacher_notes=self._filter_output(_bound_str(data.get("teacher_notes", "")), grade_s),
                )
            logger.error("报告生成失败: LLM 返回空或无法解析")
            return StudentReport(student_name=student_s, subject=subject_s, grade=grade_s, error="LLM 返回空或无法解析")
        except Exception as e:
            logger.error(f"报告生成失败: {e}")
            rethrow_if_fatal(e)
            return StudentReport(student_name=student_s, subject=subject_s, grade=grade_s, error=str(e))

    async def generate_rubric(self, assignment_type: str, grade: str, criteria: list[str] | None = None) -> dict[str, Any]:
        """生成评分标准（Rubric）。"""
        at_s = sanitize_input(assignment_type, 50)
        grade_s = sanitize_input(grade, 4)
        criteria_str = ", ".join(sanitize_input(c, 50) for c in criteria) if criteria else "内容, 结构, 语言, 创意"
        prompt = f"""为{grade_s}年级的{at_s}作业设计评分标准。

评分维度: {criteria_str}
返回JSON格式，每项包含：维度名称、分值、4个等级(优秀/良好/合格/需改进)的描述。"""
        try:
            response = await self.mlx.chat([
                {"role": "system", "content": "你是一位课程设计专家，设计清晰、可操作的评分标准。"},
                {"role": "user", "content": prompt},
            ], temperature=0.3)
            data = self._parse_json(response)
            if isinstance(data, dict):
                return data
            logger.error("评分标准生成失败: LLM 返回空或无法解析")
            return {"criteria": criteria or [], "error": "LLM 返回空或无法解析"}
        except Exception as e:
            logger.error(f"评分标准生成失败: {e}")
            rethrow_if_fatal(e)
            return {"criteria": criteria or [], "error": str(e)}

    def _parse_json(self, text: Any) -> Any:
        """解析 LLM 返回的 JSON — 容忍 None/空串/代码块围栏 (ENG-5/6)。"""
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