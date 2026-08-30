"""课程规划引擎 — 教案生成、课程设计、学习目标制定。"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .._parse import parse_json
from .._prompt import build_prompt
from ..ai_client import MLXClient
from ..errors import rethrow_if_fatal
from ..safety.filter import ContentFilter, sanitize_input

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
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v or k == "error"}


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
    error: str = ""


class CurriculumEngine:
    """课程规划引擎 — 对标 Claude K-12 Teacher 的课程设计能力。

    支持：
    - 标准对齐教案生成
    - 分层教学差异化设计
    - 跨学科项目式学习
    - 单元/学期课程规划
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
            logger.warning("教案内容检出不当, 已过滤: %s", check.summary)
            return check.filtered_text
        return text

    def _filter_dict(self, obj: Any, grade: str, depth: int = 0) -> Any:
        # P2: 递归过滤嵌套 dict/list 中的字符串值, 防 LLM 返回的 differentiation 携带不当内容直送师生。
        if depth > 5:
            return obj
        if isinstance(obj, dict):
            return {k: self._filter_dict(v, grade, depth + 1) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._filter_dict(x, grade, depth + 1) for x in obj]
        if isinstance(obj, str):
            return self._filter_output(obj, grade)
        return obj

    async def generate_lesson_plan(
        self,
        subject: str,
        grade: str,
        topic: str,
        duration: int = 45,
        standards: list[str] | None = None,
    ) -> LessonPlan:
        """生成标准对齐的教案。"""
        subject_s = sanitize_input(subject, 20)
        grade_s = sanitize_input(grade, 4)
        topic_s = sanitize_input(topic)
        if subject_s not in SUBJECTS:
            logger.warning("非标准学科: %s", subject_s)
        if grade_s not in GRADE_LEVELS:
            logger.warning("非标准年级: %s", grade_s)
        standards_str = ", ".join(sanitize_input(s, 100) for s in standards) if standards else "Common Core"
        # E12: prompt 经 build_prompt 模板层统一 sanitize 守门, 不再 f-string 手拼。
        # 已 sanitize 的字段二次过 sanitize 对干净输入幂等; duration/standards_str 非裸用户输入原样注入。
        prompt = build_prompt(
            """你是一位经验丰富的K-12教师。请为以下课程生成完整教案：

学科: {subject}
年级: {grade}
主题: {topic}
课时: {duration}分钟
课程标准: {standards}

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
}}""",
            subject=subject_s,
            grade=grade_s,
            topic=topic_s,
            duration=duration,
            standards=standards_str,
        )
        try:
            response = await self.mlx.chat([
                {"role": "system", "content": "你是一位专业K-12教师，生成符合课程标准的结构化教案。"},
                {"role": "user", "content": prompt},
            ], temperature=0.3)
            data = self._parse_json(response)
            if data:
                plan = LessonPlan(
                    id=f"lp_{int(datetime.now().timestamp())}_{uuid.uuid4().hex[:6]}",
                    subject=subject_s, grade=grade_s, title=data.get("title", topic_s),
                    duration_minutes=duration,
                    objectives=[self._filter_output(o, grade_s) for o in data.get("objectives", [])],
                    materials=[self._filter_output(m, grade_s) for m in data.get("materials", [])],
                    procedures=[
                        {k: self._filter_output(v, grade_s) if isinstance(v, str) else v
                         for k, v in p.items()}
                        for p in data.get("procedures", [])
                    ],
                    assessment=self._filter_output(data.get("assessment", ""), grade_s),
                    homework=self._filter_output(data.get("homework", ""), grade_s),
                    standards_aligned=standards or [],
                    # P2: differentiation 是 LLM 返回的嵌套 dict, 字符串值须经 _filter_output, 不直送师生。
                    differentiation=self._filter_dict(data.get("differentiation", {}), grade_s),
                    created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                )
                return plan
            logger.error("教案生成失败: LLM 返回空或无法解析")
            return LessonPlan(title=topic_s, subject=subject_s, grade=grade_s, error="LLM 返回空或无法解析")
        except Exception as e:
            logger.error(f"教案生成失败: {e}")
            rethrow_if_fatal(e)
            return LessonPlan(title=topic_s, subject=subject_s, grade=grade_s, error=str(e))

    async def generate_quiz(
        self,
        subject: str,
        grade: str,
        topic: str,
        num_questions: int = 10,
        question_types: list[str] | None = None,
    ) -> Quiz:
        """生成测验。"""
        subject_s = sanitize_input(subject, 20)
        grade_s = sanitize_input(grade, 4)
        topic_s = sanitize_input(topic)
        types = question_types or ["multiple_choice", "short_answer", "true_false"]
        prompt = f"""为{grade_s}年级{subject_s}课程生成关于"{topic_s}"的测验：

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
                # ENG-13: 题项非 dict(string/None)时跳过, points 非 int 容错, 不再崩
                # A6: 题干/选项/答案过安全过滤, 直达学生须无不当内容
                safe_q = []
                for q in questions:
                    if not isinstance(q, dict):
                        continue
                    fq = dict(q)
                    for k in ("question", "answer", "explanation"):
                        if isinstance(fq.get(k), str):
                            fq[k] = self._filter_output(fq[k], grade_s)
                    if isinstance(fq.get("options"), list):
                        fq["options"] = [
                            self._filter_output(o, grade_s) if isinstance(o, str) else o
                            for o in fq["options"]
                        ]
                    safe_q.append(fq)
                total = 0
                for q in safe_q:
                    try:
                        total += int(q.get("points", 1))
                    except (TypeError, ValueError):
                        total += 1
                return Quiz(
                    title=f"{topic_s}测验", subject=subject_s, grade=grade_s,
                    questions=safe_q,
                    total_points=total,
                    answer_key="[详见每道题目的answer字段]",
                )
            logger.error("测验生成失败: LLM 返回空或无法解析")
            return Quiz(title=f"{topic_s}测验", subject=subject_s, grade=grade_s, error="LLM 返回空或无法解析")
        except Exception as e:
            logger.error(f"测验生成失败: {e}")
            rethrow_if_fatal(e)
            return Quiz(title=f"{topic_s}测验", subject=subject_s, grade=grade_s, error=str(e))

    async def generate_unit_plan(self, subject: str, grade: str, unit_title: str, weeks: int = 4) -> dict[str, Any]:
        """生成单元教学计划。"""
        subject_s = sanitize_input(subject, 20)
        grade_s = sanitize_input(grade, 4)
        unit_s = sanitize_input(unit_title)
        prompt = f"""为{grade_s}年级{subject_s}设计一个为期{weeks}周的教学单元：
单元主题: {unit_s}
请返回JSON格式，包含每周的教学主题、学习目标、主要活动和评估方式。"""
        try:
            response = await self.mlx.chat([
                {"role": "system", "content": "你是一位课程设计专家，设计完整的单元教学计划。"},
                {"role": "user", "content": prompt},
            ], temperature=0.3)
            data = self._parse_json(response)
            if isinstance(data, dict):
                if "unit_title" not in data:
                    data["unit_title"] = unit_s
                # A6: 单元计划文本字段过安全过滤
                for k, v in list(data.items()):
                    if isinstance(v, str):
                        data[k] = self._filter_output(v, grade_s)
                return data
            logger.error("单元计划生成失败: LLM 返回空或无法解析")
            return {"unit_title": unit_s, "error": "LLM 返回空或无法解析"}
        except Exception as e:
            logger.error(f"单元计划生成失败: {e}")
            rethrow_if_fatal(e)
            return {"unit_title": unit_s, "error": str(e)}

    def _parse_json(self, text: Any) -> Any:
        # E1: 收敛至单一 _parse.parse_json, 不再各引擎手抄分叉实现
        return parse_json(text)