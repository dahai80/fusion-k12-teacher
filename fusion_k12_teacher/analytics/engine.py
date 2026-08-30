"""学情分析引擎 — 班级画像、学生画像、错题归因、补救方案。"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any

from ..ai_client import MLXClient
from ..safety.filter import sanitize_input
from ..standards.query import StandardsQuery
from .models import (
    ClassProfile,
    ErrorAnalysis,
    RemedialPlan,
    StudentAssessment,
    StudentProfile,
    WeakPoint,
)

logger = logging.getLogger(__name__)


def _coerce_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _coerce_int(val: Any, default: int = 0) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        try:
            return int(float(val))
        except (TypeError, ValueError):
            return default


def _coerce_str_list(val: Any) -> list[str]:
    if isinstance(val, list):
        return [str(x) for x in val]
    if isinstance(val, str):
        return [val]
    return []


def _extract_first_json(text: str) -> str:
    # ENG-5: 平衡括号扫描, 取首个完整 JSON 对象/数组, 替代贪婪正则 \{.*\}
    # 贪婪正则在多对象文本("{"a":1} 说明 {"b":2}")会跨界抓到无效串。
    start = -1
    close_ch = ""
    depth = 0
    in_str = False
    escape = False
    for i, c in enumerate(text):
        if in_str:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
            continue
        if c in "{[":
            if depth == 0:
                start = i
                close_ch = "}" if c == "{" else "]"
            depth += 1
        elif c in "}]":
            if depth > 0:
                depth -= 1
                if depth == 0 and start >= 0 and c == close_ch:
                    return text[start : i + 1]
    return ""


class AnalyticsEngine:
    """学情分析引擎 — 班级画像、错题归因、补救方案生成。"""

    def __init__(
        self,
        mlx: MLXClient | None = None,
        standards_query: StandardsQuery | None = None,
    ):
        self.mlx = mlx or MLXClient()
        self._standards = standards_query

    async def build_class_profile(
        self,
        class_id: str,
        subject: str,
        grade: str,
        assessments: list[StudentAssessment],
    ) -> ClassProfile:
        """生成班级学情画像。"""
        if not assessments:
            return ClassProfile(class_id=class_id, subject=subject, grade=grade)

        # ENG-4: 统计块包 try/except, 任何 _calc_* 抛错降级到空统计, 不让方法整体崩
        total_students = 0
        avg_score = 0.0
        score_distribution: dict[str, int] = {}
        weak_points: list[WeakPoint] = []
        strong_points: list[str] = []
        risk_levels: dict[str, str] = {}
        try:
            total_students = len({a.student_id for a in assessments})
            # ENG-8: 用百分比统计, 与 _calc_risk_levels 一致; 避免非百分制测验(max_score!=100)全员落入低分桶
            pcts = [a.percentage for a in assessments]
            avg_score = sum(pcts) / len(pcts) if pcts else 0.0
            score_distribution = self._calc_score_distribution(pcts)
            weak_points = self._calc_weak_points(assessments)
            strong_points = self._calc_strong_points(assessments)
            risk_levels = self._calc_risk_levels(assessments)
        except Exception as exc:
            logger.error("build_class_profile 统计计算失败, 降级到空统计: %s", exc, exc_info=True)

        summary = self._build_class_summary(
            class_id, subject, grade, total_students, avg_score,
            score_distribution, weak_points, risk_levels,
        )

        llm_err = ""
        try:
            response = await self.mlx.chat([
                {"role": "system", "content": "你是一位资深教学分析师，擅长从数据中提炼教学洞察。"},
                {"role": "user", "content": summary},
            ], temperature=0.3)
            data = self._parse_json(response)
            if isinstance(data, dict):
                llm_weak = []
                for wp in data.get("weak_knowledge_points", []):
                    if not isinstance(wp, dict):
                        continue
                    llm_weak.append(WeakPoint(
                        knowledge_point_id=str(wp.get("knowledge_point_id", "")),
                        knowledge_point_name=str(wp.get("knowledge_point_name", "")),
                        error_rate=max(0.0, min(_coerce_float(wp.get("error_rate")), 1.0)),
                        affected_students=_coerce_str_list(wp.get("affected_students")),
                        common_mistakes=_coerce_str_list(wp.get("common_mistakes")),
                        suggested_remedial=str(wp.get("suggested_remedial", "")),
                    ))
                if llm_weak:
                    weak_points = llm_weak
                llm_risk = data.get("student_risk_levels", {})
                if isinstance(llm_risk, dict) and all(
                    isinstance(k, str) and isinstance(v, str) for k, v in llm_risk.items()
                ):
                    risk_levels = {str(k): str(v) for k, v in llm_risk.items()}
            else:
                llm_err = "LLM 返回空或无法解析"
        except Exception as e:
            logger.error(f"LLM 班级画像增强失败: {e}")
            llm_err = str(e)

        return ClassProfile(
            class_id=class_id,
            subject=subject,
            grade=grade,
            period=datetime.now().strftime("%Y-%m-%d"),
            total_students=total_students,
            avg_score=round(avg_score, 1),
            score_distribution=score_distribution,
            weak_knowledge_points=weak_points,
            strong_knowledge_points=strong_points,
            student_risk_levels=risk_levels,
            generated_at=datetime.now().isoformat(),
            error=llm_err,
        )

    async def build_student_profile(
        self,
        student_id: str,
        subject: str,
        grade: str,
        history: list[StudentAssessment],
    ) -> StudentProfile:
        """生成学生个体画像。"""
        student_name = history[0].student_name if history else student_id

        if not history:
            return StudentProfile(
                student_id=student_id, name=student_name,
                subject=subject, grade=grade,
            )

        knowledge_mastery = self._calc_knowledge_mastery(history)
        avg_pct = sum(a.percentage for a in history) / len(history)

        if avg_pct >= 85:
            overall_level = "advanced"
        elif avg_pct >= 60:
            overall_level = "standard"
        else:
            overall_level = "struggling"

        trend = self._calc_trend(history)
        risk_indicators = self._calc_risk_indicators(history, avg_pct)

        history_summary = json.dumps(
            [{"date": a.date, "score": a.total_score, "max": a.max_score} for a in history[:10]],
            ensure_ascii=False,
        )

        prompt = f"""分析以下学生的学习数据，生成个性化学习画像：

学生: {student_name}({student_id})
学科: {subject} | 年级: {grade}
平均得分率: {avg_pct:.1f}%
趋势: {trend}
知识掌握度: {json.dumps(knowledge_mastery, ensure_ascii=False)}
风险指标: {risk_indicators}

考试记录: {history_summary}

返回JSON: {{
    "overall_level": "struggling/standard/advanced",
    "knowledge_mastery": {{"知识点": 掌握度0-100}},
    "learning_trend": "improving/stable/declining",
    "risk_indicators": ["风险1"],
    "recommended_actions": ["建议1"]
}}"""

        llm_err = ""
        try:
            response = await self.mlx.chat([
                {"role": "system", "content": "你是一位教育数据分析师，善于从学情数据中提炼洞察。"},
                {"role": "user", "content": prompt},
            ], temperature=0.3)
            data = self._parse_json(response)
            if isinstance(data, dict):
                llm_level = data.get("overall_level", overall_level)
                if llm_level not in ("struggling", "standard", "advanced"):
                    llm_level = overall_level
                llm_mastery = data.get("knowledge_mastery", knowledge_mastery)
                if not isinstance(llm_mastery, dict):
                    llm_mastery = knowledge_mastery
                else:
                    llm_mastery = {str(k): _coerce_float(v) for k, v in llm_mastery.items()}
                llm_trend = data.get("learning_trend", trend)
                if llm_trend not in ("improving", "stable", "declining"):
                    llm_trend = trend
                return StudentProfile(
                    student_id=student_id,
                    name=student_name,
                    grade=grade,
                    subject=subject,
                    overall_level=llm_level,
                    knowledge_mastery=llm_mastery,
                    learning_trend=llm_trend,
                    risk_indicators=_coerce_str_list(data.get("risk_indicators", risk_indicators)),
                    recommended_actions=_coerce_str_list(data.get("recommended_actions")),
                )
            llm_err = "LLM 返回空或无法解析"
        except Exception as e:
            logger.error(f"LLM 学生画像增强失败: {e}")
            llm_err = str(e)

        return StudentProfile(
            student_id=student_id,
            name=student_name,
            grade=grade,
            subject=subject,
            overall_level=overall_level,
            knowledge_mastery=knowledge_mastery,
            learning_trend=trend,
            risk_indicators=risk_indicators,
            error=llm_err,
        )

    async def analyze_errors(
        self,
        subject: str,
        grade: str,
        responses: list[dict[str, Any]],
    ) -> list[ErrorAnalysis]:
        """错题归因分析。"""
        if not responses:
            return []

        wrong = [r for r in responses if not r.get("correct", True)]
        if not wrong:
            return []

        subject_s = sanitize_input(subject, 20)
        grade_s = sanitize_input(grade, 4)
        standards_hint = ""
        if self._standards:
            points = self._standards.get_knowledge_points(subject_s, grade_s)
            if points:
                standards_hint = f"\n课标知识点参考: {', '.join(p.topic for p in points[:10])}"

        # ENG-9: wrong 中 question/student_answer 等字符串字段来自装载器, 进 prompt 前脱敏防注入
        wrong_safe = []
        for r in wrong[:20]:
            if not isinstance(r, dict):
                continue
            sr = {}
            for k, v in r.items():
                sr[k] = sanitize_input(v, 500) if isinstance(v, str) else v
            wrong_safe.append(sr)

        prompt = f"""分析以下错题数据，进行归因分析：

学科: {subject_s} | 年级: {grade_s}
错题数: {len(wrong)}
{standards_hint}

错题列表:
{json.dumps(wrong_safe, ensure_ascii=False)}

返回JSON数组，每条包含:
[
    {{
        "error_id": "err-001",
        "knowledge_point_id": "对应课标知识点ID(如有)",
        "error_type": "conceptual/procedural/careless/unknown",
        "frequency": 出现次数,
        "sample_responses": ["典型错误回答"],
        "root_cause": "根因分析",
        "remediation": "补救策略"
    }}
]"""

        try:
            response = await self.mlx.chat([
                {"role": "system", "content": "你是一位教育心理学专家，擅长错题归因和学情诊断。"},
                {"role": "user", "content": prompt},
            ], temperature=0.3)
            data = self._parse_json(response)
            if isinstance(data, list):
                out = []
                for e in data:
                    if not isinstance(e, dict):
                        continue
                    out.append(ErrorAnalysis(
                        error_id=str(e.get("error_id", "")),
                        knowledge_point_id=str(e.get("knowledge_point_id", "")),
                        error_type=str(e.get("error_type", "unknown")),
                        frequency=_coerce_int(e.get("frequency", 1), 1),
                        sample_responses=_coerce_str_list(e.get("sample_responses")),
                        root_cause=str(e.get("root_cause", "")),
                        remediation=str(e.get("remediation", "")),
                    ))
                if out:
                    return out
                logger.error("错题归因: LLM 返回空数组或无法解析，回退")
            else:
                logger.error("错题归因: LLM 返回空或无法解析，回退")
        except Exception as e:
            logger.error(f"LLM 错题归因失败: {e}")

        return [ErrorAnalysis(
            error_id="err-fallback",
            error_type="unknown",
            frequency=len(wrong),
            sample_responses=[str(r.get("student_answer", "")) for r in wrong[:3]],
            root_cause="分析失败，需人工检查",
            remediation="建议人工复核错题",
        )]

    async def generate_remedial_plan(
        self,
        student_id: str,
        subject: str,
        grade: str,
        weak_points: list[WeakPoint],
    ) -> RemedialPlan:
        """生成补救教学方案。"""
        subject_s = sanitize_input(subject, 20)
        grade_s = sanitize_input(grade, 4)
        sid_s = sanitize_input(student_id, 50)
        if not weak_points:
            return RemedialPlan(student_id=sid_s, subject=subject_s, grade=grade_s)

        standards_hint = ""
        if self._standards:
            for wp in weak_points[:3]:
                pres = self._standards.get_prerequisites(wp.knowledge_point_id)
                if pres:
                    standards_hint += f"\n{wp.knowledge_point_name} 前置知识: {', '.join(p.topic for p in pres)}"

        wp_summary = json.dumps(
            [wp.to_dict() for wp in weak_points],
            ensure_ascii=False,
        )

        prompt = f"""为学生 {sid_s} 生成补救教学方案：

学科: {subject_s} | 年级: {grade_s}
薄弱知识点: {wp_summary}
{standards_hint}

返回JSON: {{
    "strategies": ["策略1", "策略2"],
    "timeline": "建议时间线",
    "exercises": [{{"topic": "知识点", "type": "题型", "difficulty": "easy/medium", "count": 3}}],
    "estimated_duration": "预计补救时长"
}}"""

        llm_err = ""
        try:
            response = await self.mlx.chat([
                {"role": "system", "content": "你是一位经验丰富的教师，擅长设计针对性补救方案。"},
                {"role": "user", "content": prompt},
            ], temperature=0.3)
            data = self._parse_json(response)
            if isinstance(data, dict):
                raw_ex = data.get("exercises", [])
                # ENG-18: exercises 原始透传会带任意键/超长字段; 白名单键 + 有界 + 仅 dict
                exercises = []
                if isinstance(raw_ex, list):
                    for ex in raw_ex[:50]:
                        if not isinstance(ex, dict):
                            continue
                        exercises.append({
                            "topic": str(ex.get("topic", ""))[:200],
                            "type": str(ex.get("type", ""))[:50],
                            "difficulty": str(ex.get("difficulty", "medium"))[:20],
                            "count": _coerce_int(ex.get("count", 1), 1),
                        })
                return RemedialPlan(
                    student_id=sid_s,
                    subject=subject_s,
                    grade=grade_s,
                    weak_points=weak_points,
                    strategies=_coerce_str_list(data.get("strategies")),
                    timeline=str(data.get("timeline", ""))[:1000],
                    exercises=exercises,
                    estimated_duration=str(data.get("estimated_duration", ""))[:200],
                )
            llm_err = "LLM 返回空或无法解析"
        except Exception as e:
            logger.error(f"LLM 补救方案生成失败: {e}")
            llm_err = str(e)

        return RemedialPlan(
            student_id=sid_s,
            subject=subject_s,
            grade=grade_s,
            weak_points=weak_points,
            strategies=["复习基础知识", "针对性练习", "定期检测"],
            error=llm_err,
        )

    async def generate_class_report(self, class_profile: ClassProfile) -> str:
        """生成 Markdown 格式班级学情报告。"""
        # ENG-10: 班级画像字段用户可控, 进 prompt 前脱敏
        cid_s = sanitize_input(class_profile.class_id, 50)
        subject_s = sanitize_input(class_profile.subject, 20)
        grade_s = sanitize_input(class_profile.grade, 4)
        wp_str = "\n".join(
            f"  - {wp.knowledge_point_name}: 错误率 {wp.error_rate:.0%}，"
            f"影响 {len(wp.affected_students)} 人"
            for wp in class_profile.weak_knowledge_points[:5]
        )
        risk_str = "\n".join(
            f"  - {sid}: {level}"
            for sid, level in list(class_profile.student_risk_levels.items())[:5]
        )

        prompt = f"""根据以下班级学情画像，生成一份中文 Markdown 格式的教学分析报告：

班级: {cid_s}
学科: {subject_s} | 年级: {grade_s}
学生数: {class_profile.total_students}
平均分: {class_profile.avg_score}
分数分布: {json.dumps(class_profile.score_distribution, ensure_ascii=False)}

薄弱知识点:
{wp_str or '  无'}

学生风险:
{risk_str or '  无'}

优势知识点: {', '.join(class_profile.strong_knowledge_points[:5]) or '无'}

请直接返回 Markdown 格式报告，包含: 概述、学情分析、薄弱知识点分析、建议措施、后续计划。"""

        try:
            response = await self.mlx.chat([
                {"role": "system", "content": "你是一位教学督导，撰写专业、可操作的班级学情分析报告。"},
                {"role": "user", "content": prompt},
            ], temperature=0.3)
            return response.strip() if response else self._fallback_report(class_profile)
        except Exception as e:
            logger.error(f"LLM 报告生成失败: {e}")
            return self._fallback_report(class_profile)

    # ── 统计辅助方法 ──

    def _calc_score_distribution(self, pcts: list[float]) -> dict[str, int]:
        # ENG-8: 入参为百分比 (0-100), 桶阈值与百分比一致, 非百分制测验不再全员落低分桶
        dist = {"90-100": 0, "80-89": 0, "70-79": 0, "60-69": 0, "0-59": 0}
        for s in pcts:
            if s >= 90:
                dist["90-100"] += 1
            elif s >= 80:
                dist["80-89"] += 1
            elif s >= 70:
                dist["70-79"] += 1
            elif s >= 60:
                dist["60-69"] += 1
            else:
                dist["0-59"] += 1
        return dist

    def _calc_weak_points(self, assessments: list[StudentAssessment]) -> list[WeakPoint]:
        topic_stats: dict[str, dict[str, Any]] = {}
        for a in assessments:
            for resp in a.responses:
                qid = resp.get("question_id", resp.get("question", ""))
                if not qid:
                    continue
                if qid not in topic_stats:
                    topic_stats[qid] = {"total": 0, "wrong": 0, "wrong_answers": [], "students": set()}
                topic_stats[qid]["total"] += 1
                if not resp.get("correct", True):
                    topic_stats[qid]["wrong"] += 1
                    topic_stats[qid]["wrong_answers"].append(resp.get("student_answer", ""))
                    topic_stats[qid]["students"].add(a.student_id)

        weak = []
        for qid, stats in topic_stats.items():
            if stats["total"] < 2:
                continue
            error_rate = stats["wrong"] / stats["total"]
            if error_rate >= 0.3:
                weak.append(WeakPoint(
                    knowledge_point_id=qid,
                    knowledge_point_name=qid,
                    error_rate=round(error_rate, 2),
                    affected_students=list(stats["students"]),
                    common_mistakes=stats["wrong_answers"][:3],
                ))
        weak.sort(key=lambda w: w.error_rate, reverse=True)
        return weak[:10]

    def _calc_strong_points(self, assessments: list[StudentAssessment]) -> list[str]:
        topic_stats: dict[str, dict[str, int]] = {}
        for a in assessments:
            for resp in a.responses:
                qid = resp.get("question_id", resp.get("question", ""))
                if not qid:
                    continue
                if qid not in topic_stats:
                    topic_stats[qid] = {"total": 0, "correct": 0}
                topic_stats[qid]["total"] += 1
                if resp.get("correct", True):
                    topic_stats[qid]["correct"] += 1

        strong = []
        for qid, stats in topic_stats.items():
            if stats["total"] >= 2 and stats["correct"] / stats["total"] >= 0.8:
                strong.append(qid)
        return strong[:5]

    def _calc_risk_levels(self, assessments: list[StudentAssessment]) -> dict[str, str]:
        student_scores: dict[str, list[float]] = {}
        for a in assessments:
            student_scores.setdefault(a.student_id, []).append(a.percentage)

        risk = {}
        for sid, pcts in student_scores.items():
            avg = sum(pcts) / len(pcts)
            if avg < 60:
                risk[sid] = "high"
            elif avg < 75:
                risk[sid] = "medium"
            else:
                risk[sid] = "low"
        return risk

    def _calc_knowledge_mastery(self, history: list[StudentAssessment]) -> dict[str, float]:
        mastery: dict[str, list[float]] = {}
        for a in history:
            for qid, score in a.scores.items():
                mastery.setdefault(qid, []).append(score)
        return {k: round(sum(v) / len(v), 1) for k, v in mastery.items()}

    def _calc_trend(self, history: list[StudentAssessment]) -> str:
        if len(history) < 4:
            return "stable"
        sorted_h = sorted(history, key=lambda a: a.date)
        pcts = [a.percentage for a in sorted_h]
        mid = len(pcts) // 2
        first_half = sum(pcts[:mid]) / mid
        second_half = sum(pcts[mid:]) / (len(pcts) - mid)
        diff = second_half - first_half
        if diff > 5:
            return "improving"
        elif diff < -5:
            return "declining"
        return "stable"

    def _calc_risk_indicators(self, history: list[StudentAssessment], avg_pct: float) -> list[str]:
        indicators = []
        if avg_pct < 60:
            indicators.append("成绩低于及格线")
        if len(history) >= 2:
            trend = self._calc_trend(history)
            if trend == "declining":
                indicators.append("成绩呈下降趋势")
        low_scoring = [a for a in history if a.percentage < 50]
        if len(low_scoring) > len(history) * 0.3:
            indicators.append("多次低分")
        return indicators

    def _build_class_summary(
        self,
        class_id: str, subject: str, grade: str,
        total_students: int, avg_score: float,
        score_distribution: dict[str, int],
        weak_points: list[WeakPoint],
        risk_levels: dict[str, str],
    ) -> str:
        # ENG-10: class_id/subject/grade 用户可控, 进 prompt 前脱敏防注入
        class_id = sanitize_input(class_id, 50)
        subject = sanitize_input(subject, 20)
        grade = sanitize_input(grade, 4)
        wp_str = "\n".join(
            f"  - {wp.knowledge_point_name}: 错误率{wp.error_rate:.0%}"
            for wp in weak_points[:5]
        )
        high_risk = sum(1 for v in risk_levels.values() if v == "high")
        return f"""分析以下班级学情数据，补充教学洞察：

班级: {class_id} | 学科: {subject} | 年级: {grade}
学生数: {total_students}
平均分: {avg_score:.1f}
分数分布: {json.dumps(score_distribution, ensure_ascii=False)}
高风险学生: {high_risk}

统计薄弱点:
{wp_str or '  无明显薄弱点'}

请返回JSON: {{
    "weak_knowledge_points": [
        {{
            "knowledge_point_id": "知识点ID",
            "knowledge_point_name": "知识点名称",
            "error_rate": 0.5,
            "affected_students": ["学生ID"],
            "common_mistakes": ["典型错误"],
            "suggested_remedial": "建议补救措施"
        }}
    ],
    "student_risk_levels": {{"学生ID": "high/medium/low"}}
}}"""

    def _fallback_report(self, profile: ClassProfile) -> str:
        wp_lines = "\n".join(
            f"- {wp.knowledge_point_name}: 错误率 {wp.error_rate:.0%}"
            for wp in profile.weak_knowledge_points[:5]
        )
        return f"""# 班级学情报告

## 概述

- 班级: {profile.class_id}
- 学科: {profile.subject} | 年级: {profile.grade}
- 学生数: {profile.total_students}
- 平均分: {profile.avg_score}

## 分数分布

{json.dumps(profile.score_distribution, ensure_ascii=False)}

## 薄弱知识点

{wp_lines or '暂无数据'}

## 建议

- 针对薄弱知识点设计专项练习
- 关注高风险学生，安排一对一辅导
"""

    def _parse_json(self, text: Any) -> Any:
        if not isinstance(text, str) or not text.strip():
            return None
        # ENG-20: 顶部有界长度, 防超长响应撑爆解析/下游; 仅 content 路径单独 cap 不够
        if len(text) > 200000:
            logger.warning("LLM 返回过长(%d 字符), 截断后再解析", len(text))
            text = text[:200000]
        text = text.strip()
        # ENG-5: 优先取 ```json``` 代码块, 否则用平衡括号扫描取首个完整 JSON
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
        if match:
            candidate = match.group(1).strip()
        else:
            candidate = _extract_first_json(text)
        if not candidate:
            return None
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            return None
