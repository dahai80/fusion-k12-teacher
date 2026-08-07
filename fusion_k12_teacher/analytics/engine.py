"""学情分析引擎 — 班级画像、学生画像、错题归因、补救方案。"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from ..ai_client import MLXClient
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

        total_students = len({a.student_id for a in assessments})
        scores = [a.total_score for a in assessments]
        avg_score = sum(scores) / len(scores) if scores else 0.0
        score_distribution = self._calc_score_distribution(scores)

        weak_points = self._calc_weak_points(assessments)
        strong_points = self._calc_strong_points(assessments)
        risk_levels = self._calc_risk_levels(assessments)

        summary = self._build_class_summary(
            class_id, subject, grade, total_students, avg_score,
            score_distribution, weak_points, risk_levels,
        )

        try:
            response = await self.mlx.chat([
                {"role": "system", "content": "你是一位资深教学分析师，擅长从数据中提炼教学洞察。"},
                {"role": "user", "content": summary},
            ], temperature=0.3)
            data = self._parse_json(response)
            if data:
                llm_weak = [
                    WeakPoint(
                        knowledge_point_id=wp.get("knowledge_point_id", ""),
                        knowledge_point_name=wp.get("knowledge_point_name", ""),
                        error_rate=wp.get("error_rate", 0.0),
                        affected_students=wp.get("affected_students", []),
                        common_mistakes=wp.get("common_mistakes", []),
                        suggested_remedial=wp.get("suggested_remedial", ""),
                    )
                    for wp in data.get("weak_knowledge_points", [])
                ]
                if llm_weak:
                    weak_points = llm_weak
                llm_risk = data.get("student_risk_levels", {})
                if llm_risk:
                    risk_levels = llm_risk
        except Exception as e:
            logger.error(f"LLM 班级画像增强失败: {e}")

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

        try:
            response = await self.mlx.chat([
                {"role": "system", "content": "你是一位教育数据分析师，善于从学情数据中提炼洞察。"},
                {"role": "user", "content": prompt},
            ], temperature=0.3)
            data = self._parse_json(response)
            if data:
                return StudentProfile(
                    student_id=student_id,
                    name=student_name,
                    grade=grade,
                    subject=subject,
                    overall_level=data.get("overall_level", overall_level),
                    knowledge_mastery=data.get("knowledge_mastery", knowledge_mastery),
                    learning_trend=data.get("learning_trend", trend),
                    risk_indicators=data.get("risk_indicators", risk_indicators),
                    recommended_actions=data.get("recommended_actions", []),
                )
        except Exception as e:
            logger.error(f"LLM 学生画像增强失败: {e}")

        return StudentProfile(
            student_id=student_id,
            name=student_name,
            grade=grade,
            subject=subject,
            overall_level=overall_level,
            knowledge_mastery=knowledge_mastery,
            learning_trend=trend,
            risk_indicators=risk_indicators,
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

        standards_hint = ""
        if self._standards:
            points = self._standards.get_knowledge_points(subject, grade)
            if points:
                standards_hint = f"\n课标知识点参考: {', '.join(p.topic for p in points[:10])}"

        prompt = f"""分析以下错题数据，进行归因分析：

学科: {subject} | 年级: {grade}
错题数: {len(wrong)}
{standards_hint}

错题列表:
{json.dumps(wrong[:20], ensure_ascii=False)}

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
                return [
                    ErrorAnalysis(
                        error_id=e.get("error_id", ""),
                        knowledge_point_id=e.get("knowledge_point_id", ""),
                        error_type=e.get("error_type", "unknown"),
                        frequency=e.get("frequency", 1),
                        sample_responses=e.get("sample_responses", []),
                        root_cause=e.get("root_cause", ""),
                        remediation=e.get("remediation", ""),
                    )
                    for e in data
                ]
        except Exception as e:
            logger.error(f"LLM 错题归因失败: {e}")

        return [ErrorAnalysis(
            error_id="err-fallback",
            error_type="unknown",
            frequency=len(wrong),
            sample_responses=[r.get("student_answer", "") for r in wrong[:3]],
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
        if not weak_points:
            return RemedialPlan(student_id=student_id, subject=subject, grade=grade)

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

        prompt = f"""为学生 {student_id} 生成补救教学方案：

学科: {subject} | 年级: {grade}
薄弱知识点: {wp_summary}
{standards_hint}

返回JSON: {{
    "strategies": ["策略1", "策略2"],
    "timeline": "建议时间线",
    "exercises": [{{"topic": "知识点", "type": "题型", "difficulty": "easy/medium", "count": 3}}],
    "estimated_duration": "预计补救时长"
}}"""

        try:
            response = await self.mlx.chat([
                {"role": "system", "content": "你是一位经验丰富的教师，擅长设计针对性补救方案。"},
                {"role": "user", "content": prompt},
            ], temperature=0.3)
            data = self._parse_json(response)
            if data:
                return RemedialPlan(
                    student_id=student_id,
                    subject=subject,
                    grade=grade,
                    weak_points=weak_points,
                    strategies=data.get("strategies", []),
                    timeline=data.get("timeline", ""),
                    exercises=data.get("exercises", []),
                    estimated_duration=data.get("estimated_duration", ""),
                )
        except Exception as e:
            logger.error(f"LLM 补救方案生成失败: {e}")

        return RemedialPlan(
            student_id=student_id,
            subject=subject,
            grade=grade,
            weak_points=weak_points,
            strategies=["复习基础知识", "针对性练习", "定期检测"],
        )

    async def generate_class_report(self, class_profile: ClassProfile) -> str:
        """生成 Markdown 格式班级学情报告。"""
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

班级: {class_profile.class_id}
学科: {class_profile.subject} | 年级: {class_profile.grade}
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

    def _calc_score_distribution(self, scores: list[float]) -> dict[str, int]:
        dist = {"90-100": 0, "80-89": 0, "70-79": 0, "60-69": 0, "0-59": 0}
        for s in scores:
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
            if stats["total"] == 0:
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
        if len(history) < 2:
            return "stable"
        sorted_h = sorted(history, key=lambda a: a.date)
        pcts = [a.percentage for a in sorted_h]
        mid = len(pcts) // 2
        first_half = sum(pcts[:mid]) / max(mid, 1)
        second_half = sum(pcts[mid:]) / max(len(pcts) - mid, 1)
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
