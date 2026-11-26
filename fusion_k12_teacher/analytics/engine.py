"""Learning analytics engine — class profile, student profile, error attribution, remedial plans."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from .._coerce import coerce_float, coerce_int, coerce_str_list
from .._parse import parse_json
from ..ai_client import MLXClient
from ..errors import rethrow_if_fatal
from ..safety.filter import ContentFilter, sanitize_input
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


# E13: _coerce_* consolidated into the single _coerce.py implementation; aliases kept for existing in-engine calls
_coerce_float = coerce_float
_coerce_int = coerce_int
_coerce_str_list = coerce_str_list


class AnalyticsEngine:
    """Learning analytics engine — class profile, error attribution, remedial plan generation."""

    def __init__(
        self,
        mlx: MLXClient | None = None,
        standards_query: StandardsQuery | None = None,
        content_filter: ContentFilter | None = None,
    ):
        self.mlx = mlx or MLXClient()
        self._standards = standards_query
        # A6: unified safety filter across engines — LLM-generated reports/remedial strategies pass check_output before reaching students/teachers.
        self._filter = content_filter or ContentFilter()

    def _filter_output(self, text: str, grade: str) -> str:
        # A6: on hit, replace with mask and warn — never let sensitive content reach teachers/students directly.
        if not isinstance(text, str) or not text:
            return text
        check = self._filter.check_output(text, grade)
        if not check.is_safe:
            logger.warning("Inappropriate analytics content detected, filtered: %s", check.summary)
            return check.filtered_text
        return text

    @staticmethod
    def _mask_sid(sid: Any) -> str:
        # P1-2/P1-3: student IDs are PII — mask to a short hash prefix before entering prompts / API returns,
        # never persist the raw ID. Same input, same output (no salt, masking only), for aggregate stats and risk tagging.
        s = str(sid or "")
        if not s:
            return ""
        import hashlib
        return "S" + hashlib.sha1(s.encode("utf-8")).hexdigest()[:6]

    async def build_class_profile(
        self,
        class_id: str,
        subject: str,
        grade: str,
        assessments: list[StudentAssessment],
    ) -> ClassProfile:
        """Build the class learning profile."""
        if not assessments:
            return ClassProfile(class_id=class_id, subject=subject, grade=grade)

        # ENG-4: stats block wrapped in try/except — any _calc_* failure degrades to empty stats instead of crashing the whole method
        total_students = 0
        avg_score = 0.0
        score_distribution: dict[str, int] = {}
        weak_points: list[WeakPoint] = []
        strong_points: list[str] = []
        risk_levels: dict[str, str] = {}
        try:
            total_students = len({a.student_id for a in assessments})
            # ENG-8: use percentage stats, consistent with _calc_risk_levels; avoids non-percent assessments (max_score!=100) all falling into the lowest bucket
            pcts = [a.percentage for a in assessments]
            avg_score = sum(pcts) / len(pcts) if pcts else 0.0
            score_distribution = self._calc_score_distribution(pcts)
            # P3: single scan produces weak+strong, instead of calling _calc_point_stats twice (double pass over assessments×responses).
            topic_stats = self._calc_point_stats(assessments)
            weak_points = self._weak_from_stats(topic_stats)
            strong_points = self._strong_from_stats(topic_stats)
            risk_levels = self._calc_risk_levels(assessments)
        except Exception as exc:
            logger.error("build_class_profile stats calculation failed, degrading to empty stats: %s", exc, exc_info=True)
            rethrow_if_fatal(exc)

        summary = self._build_class_summary(
            class_id, subject, grade, total_students, avg_score,
            score_distribution, weak_points, risk_levels,
        )

        llm_err = ""
        try:
            response = await self.mlx.chat([
                # i18n: user-facing
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
                        knowledge_point_name=self._filter_output(str(wp.get("knowledge_point_name", "")), grade),
                        error_rate=max(0.0, min(_coerce_float(wp.get("error_rate")), 1.0)),
                        affected_students=[self._mask_sid(s) for s in _coerce_str_list(wp.get("affected_students"))],
                        common_mistakes=[
                            self._filter_output(m, grade) for m in _coerce_str_list(wp.get("common_mistakes"))
                        ],
                        suggested_remedial=self._filter_output(str(wp.get("suggested_remedial", "")), grade),
                    ))
                if llm_weak:
                    weak_points = llm_weak
                llm_risk = data.get("student_risk_levels", {})
                if isinstance(llm_risk, dict) and all(
                    isinstance(k, str) and isinstance(v, str) for k, v in llm_risk.items()
                ):
                    risk_levels = {str(k): str(v) for k, v in llm_risk.items()}
            else:
                llm_err = "LLM returned empty or unparseable output"
        except Exception as e:
            logger.error(f"LLM class profile enrichment failed: {e}")
            rethrow_if_fatal(e)
            llm_err = str(e)

        # E14: single now snapshot — the original two datetime.now() calls were non-atomic; across midnight
        # period(day N) and generated_at(day N+1) diverged. One read guarantees the same instant.
        now = datetime.now()
        # P1-2: student risk keys contain raw student IDs (PII) — mask uniformly before leaving the engine, so neither API returns nor report prompts persist raw IDs.
        masked_risk = {self._mask_sid(k): v for k, v in risk_levels.items()}
        return ClassProfile(
            class_id=class_id,
            subject=subject,
            grade=grade,
            period=now.strftime("%Y-%m-%d"),
            total_students=total_students,
            avg_score=round(avg_score, 1),
            score_distribution=score_distribution,
            weak_knowledge_points=weak_points,
            strong_knowledge_points=strong_points,
            student_risk_levels=masked_risk,
            generated_at=now.isoformat(),
            error=llm_err,
        )

    async def build_student_profile(
        self,
        student_id: str,
        subject: str,
        grade: str,
        history: list[StudentAssessment],
    ) -> StudentProfile:
        """Build the individual student profile."""
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

        # i18n: user-facing
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
                # i18n: user-facing
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
                    risk_indicators=[
                        self._filter_output(r, grade) for r in _coerce_str_list(data.get("risk_indicators", risk_indicators))
                    ],
                    recommended_actions=[
                        self._filter_output(a, grade) for a in _coerce_str_list(data.get("recommended_actions"))
                    ],
                )
            llm_err = "LLM returned empty or unparseable output"
        except Exception as e:
            logger.error(f"LLM student profile enrichment failed: {e}")
            rethrow_if_fatal(e)
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
        """Attribute analysis of wrong answers."""
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
                # i18n: user-facing
                standards_hint = f"\n课标知识点参考: {', '.join(p.topic for p in points[:10])}"

        # ENG-9: string fields in wrong (question/student_answer etc.) come from the loader — sanitize before entering the prompt to prevent injection
        wrong_safe = []
        for r in wrong[:20]:
            if not isinstance(r, dict):
                continue
            sr = {}
            for k, v in r.items():
                sr[k] = sanitize_input(v, 500) if isinstance(v, str) else v
            wrong_safe.append(sr)

        # i18n: user-facing
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
                # i18n: user-facing
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
                        sample_responses=[
                            self._filter_output(s, grade_s) for s in _coerce_str_list(e.get("sample_responses"))
                        ],
                        root_cause=self._filter_output(str(e.get("root_cause", "")), grade_s),
                        remediation=self._filter_output(str(e.get("remediation", "")), grade_s),
                    ))
                if out:
                    return out
                logger.error("Error attribution: LLM returned empty array or unparseable output, falling back")
            else:
                logger.error("Error attribution: LLM returned empty or unparseable output, falling back")
        except Exception as e:
            logger.error(f"LLM error attribution failed: {e}")
            rethrow_if_fatal(e)

        return [ErrorAnalysis(
            error_id="err-fallback",
            error_type="unknown",
            frequency=len(wrong),
            # P1-1: degraded fallback never persists raw student answers (PII) — placeholders only, keep the sample count; raw text stays out of API returns.
            # i18n: user-facing
            sample_responses=[f"<作答样本{i+1} 已脱敏>" for i in range(min(3, len(wrong)))],
            # i18n: user-facing
            root_cause="分析失败，需人工检查",
            # i18n: user-facing
            remediation="建议人工复核错题",
        )]

    async def generate_remedial_plan(
        self,
        student_id: str,
        subject: str,
        grade: str,
        weak_points: list[WeakPoint],
    ) -> RemedialPlan:
        """Generate a remedial teaching plan."""
        subject_s = sanitize_input(subject, 20)
        grade_s = sanitize_input(grade, 4)
        sid_s = sanitize_input(student_id, 50)
        # P1-17: daily_homework_review passes analyze_errors' list[ErrorAnalysis] in as weak_points;
        # ErrorAnalysis lacks knowledge_point_name/to_dict → AttributeError swallowed into an empty plan.
        # Normalize to WeakPoint uniformly: objects missing the interface map from ErrorAnalysis fields, no more crash.
        weak_points = [self._to_weak_point(w) for w in weak_points] if weak_points else []
        if not weak_points:
            return RemedialPlan(student_id=sid_s, subject=subject_s, grade=grade_s)

        standards_hint = ""
        if self._standards:
            for wp in weak_points[:3]:
                pres = self._standards.get_prerequisites(wp.knowledge_point_id)
                if pres:
                    # i18n: user-facing
                    standards_hint += f"\n{wp.knowledge_point_name} 前置知识: {', '.join(p.topic for p in pres)}"

        wp_summary = json.dumps(
            [wp.to_dict() for wp in weak_points],
            ensure_ascii=False,
        )

        # i18n: user-facing
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
                # i18n: user-facing
                {"role": "system", "content": "你是一位经验丰富的教师，擅长设计针对性补救方案。"},
                {"role": "user", "content": prompt},
            ], temperature=0.3)
            data = self._parse_json(response)
            if isinstance(data, dict):
                raw_ex = data.get("exercises", [])
                # ENG-18: passing exercises through raw would carry arbitrary keys/oversized fields; whitelist keys + bounded + dicts only
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
                    strategies=[
                        self._filter_output(s, grade_s) for s in _coerce_str_list(data.get("strategies"))
                    ],
                    timeline=self._filter_output(str(data.get("timeline", ""))[:1000], grade_s),
                    exercises=exercises,
                    estimated_duration=self._filter_output(str(data.get("estimated_duration", ""))[:200], grade_s),
                )
            llm_err = "LLM returned empty or unparseable output"
        except Exception as e:
            logger.error(f"LLM remedial plan generation failed: {e}")
            rethrow_if_fatal(e)
            llm_err = str(e)

        return RemedialPlan(
            student_id=sid_s,
            subject=subject_s,
            grade=grade_s,
            weak_points=weak_points,
            # i18n: user-facing
            strategies=["复习基础知识", "针对性练习", "定期检测"],
            error=llm_err,
        )

    async def generate_class_report(self, class_profile: ClassProfile) -> str:
        """Generate a Markdown-format class learning report."""
        # ENG-10: class profile fields are user-controlled — sanitize before entering the prompt
        cid_s = sanitize_input(class_profile.class_id, 50)
        subject_s = sanitize_input(class_profile.subject, 20)
        grade_s = sanitize_input(class_profile.grade, 4)
        # i18n: user-facing
        wp_str = "\n".join(
            f"  - {wp.knowledge_point_name}: 错误率 {wp.error_rate:.0%}，"
            f"影响 {len(wp.affected_students)} 人"
            for wp in class_profile.weak_knowledge_points[:5]
        )
        risk_str = "\n".join(
            f"  - {self._mask_sid(sid)}: {level}"
            for sid, level in list(class_profile.student_risk_levels.items())[:5]
        )

        # i18n: user-facing
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
                # i18n: user-facing
                {"role": "system", "content": "你是一位教学督导，撰写专业、可操作的班级学情分析报告。"},
                {"role": "user", "content": prompt},
            ], temperature=0.3)
            if response and response.strip():
                # A6: raw LLM class report passes the safety filter before reaching teachers
                return self._filter_output(response.strip(), grade_s)
            return self._fallback_report(class_profile)
        except Exception as e:
            logger.error(f"LLM report generation failed: {e}")
            rethrow_if_fatal(e)
            return self._fallback_report(class_profile)

    # ── Statistics helpers ──

    def _to_weak_point(self, item: Any) -> WeakPoint:
        # P1-17: normalize the incoming object to WeakPoint — supports ErrorAnalysis (no knowledge_point_name/to_dict).
        if isinstance(item, WeakPoint):
            return item
        if isinstance(item, dict):
            return WeakPoint(
                knowledge_point_id=str(item.get("knowledge_point_id", "")),
                knowledge_point_name=str(item.get("knowledge_point_name", item.get("error_type", ""))),
                error_rate=float(item.get("error_rate", 0.5)),
            )
        # ErrorAnalysis-like: read fields via duck typing
        kp_name = getattr(item, "knowledge_point_name", "") or getattr(item, "error_type", "")
        kp_id = getattr(item, "knowledge_point_id", "")
        freq = getattr(item, "frequency", 1)
        return WeakPoint(
            knowledge_point_id=str(kp_id or ""),
            knowledge_point_name=str(kp_name or "unknown"),
            error_rate=min(1.0, float(freq) / 10.0) if freq else 0.5,
        )

    def _calc_score_distribution(self, pcts: list[float]) -> dict[str, int]:
        # ENG-8: input is percentages (0-100), bucket thresholds match percentages; non-percent assessments no longer all fall into the lowest bucket
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

    def _calc_point_stats(self, assessments: list[StudentAssessment]) -> dict[str, dict[str, Any]]:
        # P3: single scan over assessments×responses collects all fields needed for both weak/strong stats,
        # replacing the old double scan of _calc_weak_points + _calc_strong_points (1000 students × 50 questions, two passes).
        topic_stats: dict[str, dict[str, Any]] = {}
        for a in assessments:
            for resp in a.responses:
                qid = resp.get("question_id", resp.get("question", ""))
                if not qid:
                    continue
                if qid not in topic_stats:
                    topic_stats[qid] = {
                        "total": 0, "wrong": 0, "correct": 0,
                        "wrong_answers": [], "students": set(),
                    }
                stats = topic_stats[qid]
                stats["total"] += 1
                if resp.get("correct", True):
                    stats["correct"] += 1
                else:
                    stats["wrong"] += 1
                    stats["wrong_answers"].append(resp.get("student_answer", ""))
                    stats["students"].add(a.student_id)
        return topic_stats

    def _weak_from_stats(self, topic_stats: dict[str, dict[str, Any]]) -> list[WeakPoint]:
        weak = []
        for qid, stats in topic_stats.items():
            if stats["total"] < 2:
                continue
            error_rate = stats["wrong"] / stats["total"]
            if error_rate >= 0.3:
                # E15: qid is the question number (question_id), not a knowledge point ID —
                # leave knowledge_point_id empty for curriculum alignment to fill; no more impersonating a KP ID with a question number.
                weak.append(WeakPoint(
                    question_id=qid,
                    knowledge_point_id="",
                    knowledge_point_name=qid,
                    error_rate=round(error_rate, 2),
                    affected_students=[self._mask_sid(s) for s in stats["students"]],
                    common_mistakes=stats["wrong_answers"][:3],
                ))
        weak.sort(key=lambda w: w.error_rate, reverse=True)
        return weak[:10]

    def _strong_from_stats(self, topic_stats: dict[str, dict[str, Any]]) -> list[str]:
        strong = []
        for qid, stats in topic_stats.items():
            if stats["total"] >= 2 and stats["correct"] / stats["total"] >= 0.8:
                strong.append(qid)
        return strong[:5]

    def _calc_weak_points(self, assessments: list[StudentAssessment]) -> list[WeakPoint]:
        # Public entry point (called directly by tests) — its own scan; build_class_profile uses the merged path to avoid a double pass.
        return self._weak_from_stats(self._calc_point_stats(assessments))

    def _calc_strong_points(self, assessments: list[StudentAssessment]) -> list[str]:
        return self._strong_from_stats(self._calc_point_stats(assessments))

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
            # i18n: user-facing
            indicators.append("成绩低于及格线")
        if len(history) >= 2:
            trend = self._calc_trend(history)
            if trend == "declining":
                # i18n: user-facing
                indicators.append("成绩呈下降趋势")
        low_scoring = [a for a in history if a.percentage < 50]
        # ENG-21: small-sample false positive — 1 low score out of 3 (1>0.9) already reported "repeated low scores".
        # Require len(history)>=3 and >=2 absolute low scores, so a single fluke is never judged "repeated".
        if len(history) >= 3 and len(low_scoring) >= 2 and len(low_scoring) > len(history) * 0.3:
            # i18n: user-facing
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
        # ENG-10: class_id/subject/grade are user-controlled — sanitize before entering the prompt to prevent injection
        class_id = sanitize_input(class_id, 50)
        subject = sanitize_input(subject, 20)
        grade = sanitize_input(grade, 4)
        # i18n: user-facing
        wp_str = "\n".join(
            f"  - {wp.knowledge_point_name}: 错误率{wp.error_rate:.0%}"
            for wp in weak_points[:5]
        )
        high_risk = sum(1 for v in risk_levels.values() if v == "high")
        # i18n: user-facing
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
        # i18n: user-facing
        wp_lines = "\n".join(
            f"- {wp.knowledge_point_name}: 错误率 {wp.error_rate:.0%}"
            for wp in profile.weak_knowledge_points[:5]
        )
        # i18n: user-facing
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
        # E1: consolidated into the single _parse.parse_json — bounded length + balanced-brace scan + fence extraction
        # (the original local _extract_first_json moved to _parse.py, shared by all engines)
        return parse_json(text)
