"""学情分析引擎 — 班级画像、学生画像、错题归因、补救方案。"""

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


# E13: _coerce_* 收敛至 _coerce.py 单实现, 保留别名兼容引擎内既有调用
_coerce_float = coerce_float
_coerce_int = coerce_int
_coerce_str_list = coerce_str_list


class AnalyticsEngine:
    """学情分析引擎 — 班级画像、错题归因、补救方案生成。"""

    def __init__(
        self,
        mlx: MLXClient | None = None,
        standards_query: StandardsQuery | None = None,
        content_filter: ContentFilter | None = None,
    ):
        self.mlx = mlx or MLXClient()
        self._standards = standards_query
        # A6: 全引擎统一安全过滤 — LLM 生成报告/补救策略送学生/教师前过 check_output。
        self._filter = content_filter or ContentFilter()

    def _filter_output(self, text: str, grade: str) -> str:
        # A6: 命中不当内容替换掩码并告警, 不让敏感内容直达师生。
        if not isinstance(text, str) or not text:
            return text
        check = self._filter.check_output(text, grade)
        if not check.is_safe:
            logger.warning("学情分析内容检出不当, 已过滤: %s", check.summary)
            return check.filtered_text
        return text

    @staticmethod
    def _mask_sid(sid: Any) -> str:
        # P1-2/P1-3: 学生 ID 属 PII, 进 prompt / 入 API 返回前脱敏为短哈希前缀,
        # 不落原始 ID。同输入同输出 (无 salt, 仅遮蔽), 供聚合统计与风险标注。
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
            # P3: 单遍扫描得 weak+strong, 不再各调一遍 _calc_point_stats (双遍 assessments×responses)。
            topic_stats = self._calc_point_stats(assessments)
            weak_points = self._weak_from_stats(topic_stats)
            strong_points = self._strong_from_stats(topic_stats)
            risk_levels = self._calc_risk_levels(assessments)
        except Exception as exc:
            logger.error("build_class_profile 统计计算失败, 降级到空统计: %s", exc, exc_info=True)
            rethrow_if_fatal(exc)

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
                llm_err = "LLM 返回空或无法解析"
        except Exception as e:
            logger.error(f"LLM 班级画像增强失败: {e}")
            rethrow_if_fatal(e)
            llm_err = str(e)

        # E14: 单一 now 快照 — 原两次 datetime.now() 非原子, 跨午夜时 period(前一天)
        # 与 generated_at(后一天) 不一致。一次取值保证同一时刻。
        now = datetime.now()
        # P1-2: 学生风险键含原始学生 ID (PII), 出引擎前统一脱敏 — API 返回 + 报告 prompt 都不再落原始 ID。
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
                    risk_indicators=[
                        self._filter_output(r, grade) for r in _coerce_str_list(data.get("risk_indicators", risk_indicators))
                    ],
                    recommended_actions=[
                        self._filter_output(a, grade) for a in _coerce_str_list(data.get("recommended_actions"))
                    ],
                )
            llm_err = "LLM 返回空或无法解析"
        except Exception as e:
            logger.error(f"LLM 学生画像增强失败: {e}")
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
                        sample_responses=[
                            self._filter_output(s, grade_s) for s in _coerce_str_list(e.get("sample_responses"))
                        ],
                        root_cause=self._filter_output(str(e.get("root_cause", "")), grade_s),
                        remediation=self._filter_output(str(e.get("remediation", "")), grade_s),
                    ))
                if out:
                    return out
                logger.error("错题归因: LLM 返回空数组或无法解析，回退")
            else:
                logger.error("错题归因: LLM 返回空或无法解析，回退")
        except Exception as e:
            logger.error(f"LLM 错题归因失败: {e}")
            rethrow_if_fatal(e)

        return [ErrorAnalysis(
            error_id="err-fallback",
            error_type="unknown",
            frequency=len(wrong),
            # P1-1: 降级回退不落原始学生作答 (PII), 仅占位保留样本数, 原文不入 API 返回。
            sample_responses=[f"<作答样本{i+1} 已脱敏>" for i in range(min(3, len(wrong)))],
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
        # P1-17: daily_homework_review 把 analyze_errors 的 list[ErrorAnalysis] 当 weak_points 传入,
        # ErrorAnalysis 无 knowledge_point_name/to_dict → AttributeError 被吞成空方案。
        # 统一规整为 WeakPoint: 缺接口者从 ErrorAnalysis 字段映射, 不再崩。
        weak_points = [self._to_weak_point(w) for w in weak_points] if weak_points else []
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
                    strategies=[
                        self._filter_output(s, grade_s) for s in _coerce_str_list(data.get("strategies"))
                    ],
                    timeline=self._filter_output(str(data.get("timeline", ""))[:1000], grade_s),
                    exercises=exercises,
                    estimated_duration=self._filter_output(str(data.get("estimated_duration", ""))[:200], grade_s),
                )
            llm_err = "LLM 返回空或无法解析"
        except Exception as e:
            logger.error(f"LLM 补救方案生成失败: {e}")
            rethrow_if_fatal(e)
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
            f"  - {self._mask_sid(sid)}: {level}"
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
            if response and response.strip():
                # A6: 班级报告 LLM 原文送教师前过安全过滤
                return self._filter_output(response.strip(), grade_s)
            return self._fallback_report(class_profile)
        except Exception as e:
            logger.error(f"LLM 报告生成失败: {e}")
            rethrow_if_fatal(e)
            return self._fallback_report(class_profile)

    # ── 统计辅助方法 ──

    def _to_weak_point(self, item: Any) -> WeakPoint:
        # P1-17: 规整传入对象为 WeakPoint — 支持 ErrorAnalysis (无 knowledge_point_name/to_dict)。
        if isinstance(item, WeakPoint):
            return item
        if isinstance(item, dict):
            return WeakPoint(
                knowledge_point_id=str(item.get("knowledge_point_id", "")),
                knowledge_point_name=str(item.get("knowledge_point_name", item.get("error_type", ""))),
                error_rate=float(item.get("error_rate", 0.5)),
            )
        # ErrorAnalysis-like: duck-type 读字段
        kp_name = getattr(item, "knowledge_point_name", "") or getattr(item, "error_type", "")
        kp_id = getattr(item, "knowledge_point_id", "")
        freq = getattr(item, "frequency", 1)
        return WeakPoint(
            knowledge_point_id=str(kp_id or ""),
            knowledge_point_name=str(kp_name or "unknown"),
            error_rate=min(1.0, float(freq) / 10.0) if freq else 0.5,
        )

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

    def _calc_point_stats(self, assessments: list[StudentAssessment]) -> dict[str, dict[str, Any]]:
        # P3: 单遍扫描 assessments×responses 同时统计 weak/strong 所需字段,
        # 替代原 _calc_weak_points + _calc_strong_points 各扫一遍 (1000生×50题 双遍)。
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
                # E15: qid 是题号(question_id), 非知识点 ID —
                # knowledge_point_id 留空待课标对齐填充, 不再用题号冒充。
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
        # 公开入口 (测试直调) — 单独扫一遍; build_class_profile 走合并路径免双遍。
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
            indicators.append("成绩低于及格线")
        if len(history) >= 2:
            trend = self._calc_trend(history)
            if trend == "declining":
                indicators.append("成绩呈下降趋势")
        low_scoring = [a for a in history if a.percentage < 50]
        # ENG-21: 小样本误报 — 3 条里 1 低分(1>0.9) 即报"多次低分"。
        # 要求 len(history)>=3 且绝对低分>=2, 杜绝 1 次偶发被判"多次"。
        if len(history) >= 3 and len(low_scoring) >= 2 and len(low_scoring) > len(history) * 0.3:
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
        # E1: 收敛至单一 _parse.parse_json — 含有界长度+平衡括号扫描+围栏提取
        # (原本地 _extract_first_json 已迁至 _parse.py, 各引擎共用同一实现)
        return parse_json(text)
