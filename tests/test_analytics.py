"""学情分析模块全覆盖测试 — models, loader, engine。"""

from __future__ import annotations

import json
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest

from fusion_k12_teacher.analytics.engine import AnalyticsEngine
from fusion_k12_teacher.analytics.loader import load_from_csv, load_from_json, normalize_assessments
from fusion_k12_teacher.analytics.models import (
    ClassProfile,
    ErrorAnalysis,
    RemedialPlan,
    StudentAssessment,
    StudentProfile,
    WeakPoint,
)

# ══════════════════════════════════════════════════════════════════════════════
# Models 测试
# ══════════════════════════════════════════════════════════════════════════════

class TestModels:
    def test_student_assessment_percentage(self):
        a = StudentAssessment(
            student_id="S001", student_name="张三",
            assessment_id="M1", subject="数学", grade="三年级",
            date="2024-01-01", total_score=85, max_score=100,
        )
        assert a.percentage == 85.0

    def test_student_assessment_zero_max(self):
        a = StudentAssessment(
            student_id="S001", student_name="张三",
            assessment_id="M1", subject="数学", grade="三年级",
            date="2024-01-01", total_score=0, max_score=0,
        )
        assert a.percentage == 0.0

    def test_weak_point_to_dict(self):
        wp = WeakPoint(
            knowledge_point_id="kp1",
            knowledge_point_name="分数加减",
            error_rate=0.6,
            affected_students=["S001", "S002"],
            common_mistakes=["通分错误"],
            suggested_remedial="加强通分练习",
        )
        d = wp.to_dict()
        assert d["knowledge_point_id"] == "kp1"
        assert d["error_rate"] == 0.6
        assert len(d["affected_students"]) == 2

    def test_weak_point_from_dict(self):
        d = {
            "knowledge_point_id": "kp1",
            "knowledge_point_name": "分数加减",
            "error_rate": 0.5,
            "affected_students": ["S001"],
            "common_mistakes": ["错1"],
            "suggested_remedial": "补救",
        }
        wp = WeakPoint.from_dict(d)
        assert wp.knowledge_point_id == "kp1"
        assert wp.error_rate == 0.5

    def test_class_profile_round_trip(self):
        cp = ClassProfile(
            class_id="C1", subject="数学", grade="三年级",
            period="2024-01", total_students=30, avg_score=78.5,
            score_distribution={"90-100": 5, "80-89": 10, "70-79": 8, "60-69": 4, "0-59": 3},
            weak_knowledge_points=[],
            strong_knowledge_points=["计算"],
            student_risk_levels={"S001": "high"},
            generated_at="2024-01-01T00:00:00",
        )
        d = cp.to_dict()
        cp2 = ClassProfile.from_dict(d)
        assert cp2.class_id == "C1"
        assert cp2.total_students == 30
        assert cp2.score_distribution["80-89"] == 10

    def test_student_profile_defaults(self):
        sp = StudentProfile(student_id="S001", name="张三", grade="三年级", subject="数学")
        assert sp.overall_level == "standard"
        assert sp.knowledge_mastery == {}
        assert sp.learning_trend == "stable"
        assert sp.risk_indicators == []
        assert sp.recommended_actions == []

    def test_error_analysis_creation(self):
        ea = ErrorAnalysis(
            error_id="e1", knowledge_point_id="kp1",
            error_type="conceptual", frequency=5,
            sample_responses=["答1"], root_cause="概念不清",
            remediation="重讲概念",
        )
        d = ea.to_dict()
        assert d["error_type"] == "conceptual"
        ea2 = ErrorAnalysis.from_dict(d)
        assert ea2.frequency == 5

    def test_remedial_plan_defaults(self):
        rp = RemedialPlan(student_id="S001", subject="数学", grade="三年级")
        assert rp.weak_points == []
        assert rp.strategies == []
        assert rp.timeline == ""
        assert rp.exercises == []

    def test_remedial_plan_with_weak_points(self):
        wp = WeakPoint(
            knowledge_point_id="kp1", knowledge_point_name="分数",
            error_rate=0.7, affected_students=["S001"],
        )
        rp = RemedialPlan(
            student_id="S001", subject="数学", grade="三年级",
            weak_points=[wp], strategies=["复习", "练习"],
            timeline="2周", exercises=[{"topic": "分数", "count": 5}],
            estimated_duration="2周",
        )
        d = rp.to_dict()
        rp2 = RemedialPlan.from_dict(d)
        assert len(rp2.weak_points) == 1
        assert rp2.weak_points[0].knowledge_point_name == "分数"


# ══════════════════════════════════════════════════════════════════════════════
# Loader 测试
# ══════════════════════════════════════════════════════════════════════════════

class TestLoader:
    def test_load_json_array_format(self):
        data = [{
            "student_id": "S001", "student_name": "张三",
            "assessment_id": "M1", "subject": "数学", "grade": "三年级",
            "date": "2024-01-01", "total_score": 85, "max_score": 100,
        }]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f, ensure_ascii=False)
            f.flush()
            path = f.name
        try:
            result = load_from_json(path)
            assert len(result) == 1
            assert result[0].student_id == "S001"
            assert result[0].percentage == 85.0
        finally:
            os.unlink(path)

    def test_load_json_object_format_assessments_key(self):
        data = {"assessments": [{
            "student_id": "S002", "student_name": "李四",
            "assessment_id": "M1", "subject": "数学", "grade": "三年级",
            "date": "2024-01-01", "total_score": 92, "max_score": 100,
        }]}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f, ensure_ascii=False)
            f.flush()
            path = f.name
        try:
            result = load_from_json(path)
            assert len(result) == 1
            assert result[0].student_id == "S002"
        finally:
            os.unlink(path)

    def test_load_json_object_format_records_key(self):
        data = {"records": [{
            "student_id": "S003", "student_name": "王五",
            "assessment_id": "M1", "subject": "数学", "grade": "三年级",
            "date": "2024-01-01", "total_score": 58, "max_score": 100,
        }]}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f, ensure_ascii=False)
            f.flush()
            path = f.name
        try:
            result = load_from_json(path)
            assert len(result) == 1
        finally:
            os.unlink(path)

    def test_load_json_invalid_structure(self):
        data = {"foo": "bar"}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            f.flush()
            path = f.name
        try:
            result = load_from_json(path)
            assert result == []
        finally:
            os.unlink(path)

    def test_load_csv_basic(self):
        csv_content = (
            "student_id,student_name,assessment_id,subject,grade,date,question_id,correct,student_answer,total_score,max_score\n"
            "S001,张三,M1,数学,三年级,2024-01-01,分数加减,true,3/4,85,100\n"
            "S001,张三,M1,数学,三年级,2024-01-01,分数乘除,false,2/3,85,100\n"
            "S002,李四,M1,数学,三年级,2024-01-01,分数加减,true,3/4,92,100\n"
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv_content)
            f.flush()
            path = f.name
        try:
            result = load_from_csv(path)
            assert len(result) == 2
            assert result[0].student_id == "S001"
            assert len(result[0].responses) == 2
            assert result[1].student_id == "S002"
        finally:
            os.unlink(path)

    def test_normalize_assessments_skips_invalid(self):
        raw = [
            {"student_id": "", "student_name": "空ID", "assessment_id": "M1",
             "subject": "数学", "grade": "三年级", "date": "2024-01-01",
             "total_score": 50, "max_score": 100},
            {"student_id": "S001", "student_name": "张三", "assessment_id": "M1",
             "subject": "数学", "grade": "三年级", "date": "2024-01-01",
             "total_score": 85, "max_score": 100},
        ]
        result = normalize_assessments(raw)
        assert len(result) == 1
        assert result[0].student_id == "S001"

    def test_load_sample_assessments_file(self):
        sample_path = os.path.join(
            os.path.dirname(__file__), "..",
            "fusion_k12_teacher", "analytics", "data", "sample_assessments.json",
        )
        # TEST-9: 样本文件是已提交前置数据, 非可选; 缺失即 fail-loud,
        # 不再 pytest.skip 静默丢失覆盖信号(删除即误判全绿)。
        assert os.path.exists(sample_path), f"样本数据文件缺失: {sample_path}"
        result = load_from_json(sample_path)
        assert len(result) >= 3
        assert result[0].student_id == "S001"


# ══════════════════════════════════════════════════════════════════════════════
# Engine 统计方法测试
# ══════════════════════════════════════════════════════════════════════════════

class TestAnalyticsEngineStats:
    def setup_method(self):
        self.engine = AnalyticsEngine()

    def test_score_distribution(self):
        scores = [95, 88, 75, 62, 45, 100, 80, 72]
        dist = self.engine._calc_score_distribution(scores)
        assert dist["90-100"] == 2
        assert dist["80-89"] == 2
        assert dist["70-79"] == 2
        assert dist["60-69"] == 1
        assert dist["0-59"] == 1

    def test_weak_points_calculation(self):
        assessments = [
            StudentAssessment(
                student_id="S001", student_name="张三",
                assessment_id="M1", subject="数学", grade="三年级",
                date="2024-01-01", total_score=50, max_score=100,
                responses=[
                    {"question_id": "分数加减", "correct": False, "student_answer": "1/2"},
                    {"question_id": "分数乘除", "correct": False, "student_answer": "1/3"},
                ],
            ),
            StudentAssessment(
                student_id="S002", student_name="李四",
                assessment_id="M1", subject="数学", grade="三年级",
                date="2024-01-01", total_score=80, max_score=100,
                responses=[
                    {"question_id": "分数加减", "correct": True, "student_answer": "3/4"},
                    {"question_id": "分数乘除", "correct": False, "student_answer": "2/5"},
                ],
            ),
        ]
        weak = self.engine._calc_weak_points(assessments)
        assert len(weak) >= 1
        wp_ids = [wp.knowledge_point_id for wp in weak]
        assert "分数加减" in wp_ids or "分数乘除" in wp_ids

    def test_strong_points_calculation(self):
        assessments = [
            StudentAssessment(
                student_id="S001", student_name="张三",
                assessment_id="M1", subject="数学", grade="三年级",
                date="2024-01-01", total_score=90, max_score=100,
                responses=[
                    {"question_id": "计算", "correct": True, "student_answer": "42"},
                    {"question_id": "计算", "correct": True, "student_answer": "100"},
                ],
            ),
            StudentAssessment(
                student_id="S002", student_name="李四",
                assessment_id="M1", subject="数学", grade="三年级",
                date="2024-01-01", total_score=85, max_score=100,
                responses=[
                    {"question_id": "计算", "correct": True, "student_answer": "42"},
                ],
            ),
        ]
        strong = self.engine._calc_strong_points(assessments)
        assert "计算" in strong

    def test_risk_levels(self):
        assessments = [
            StudentAssessment(
                student_id="S001", student_name="张三",
                assessment_id="M1", subject="数学", grade="三年级",
                date="2024-01-01", total_score=45, max_score=100,
            ),
            StudentAssessment(
                student_id="S002", student_name="李四",
                assessment_id="M1", subject="数学", grade="三年级",
                date="2024-01-01", total_score=70, max_score=100,
            ),
            StudentAssessment(
                student_id="S003", student_name="王五",
                assessment_id="M1", subject="数学", grade="三年级",
                date="2024-01-01", total_score=95, max_score=100,
            ),
        ]
        risk = self.engine._calc_risk_levels(assessments)
        assert risk["S001"] == "high"
        assert risk["S002"] == "medium"
        assert risk["S003"] == "low"

    def test_knowledge_mastery(self):
        history = [
            StudentAssessment(
                student_id="S001", student_name="张三",
                assessment_id="M1", subject="数学", grade="三年级",
                date="2024-01-01", total_score=80, max_score=100,
                scores={"计算": 18, "几何": 15},
            ),
            StudentAssessment(
                student_id="S001", student_name="张三",
                assessment_id="M2", subject="数学", grade="三年级",
                date="2024-02-01", total_score=85, max_score=100,
                scores={"计算": 20, "几何": 16},
            ),
        ]
        mastery = self.engine._calc_knowledge_mastery(history)
        assert "计算" in mastery
        assert mastery["计算"] == 19.0

    def test_trend_improving(self):
        history = [
            StudentAssessment(student_id="S001", student_name="张三",
                assessment_id=f"M{i}", subject="数学", grade="三年级",
                date=f"2024-0{i+1}-01", total_score=50+i*10, max_score=100)
            for i in range(4)
        ]
        assert self.engine._calc_trend(history) == "improving"

    def test_trend_declining(self):
        history = [
            StudentAssessment(student_id="S001", student_name="张三",
                assessment_id=f"M{i}", subject="数学", grade="三年级",
                date=f"2024-0{i+1}-01", total_score=90-i*10, max_score=100)
            for i in range(4)
        ]
        assert self.engine._calc_trend(history) == "declining"

    def test_trend_stable(self):
        history = [
            StudentAssessment(student_id="S001", student_name="张三",
                assessment_id=f"M{i}", subject="数学", grade="三年级",
                date=f"2024-0{i+1}-01", total_score=80, max_score=100)
            for i in range(4)
        ]
        assert self.engine._calc_trend(history) == "stable"

    def test_trend_single_assessment(self):
        history = [
            StudentAssessment(student_id="S001", student_name="张三",
                assessment_id="M1", subject="数学", grade="三年级",
                date="2024-01-01", total_score=80, max_score=100)
        ]
        assert self.engine._calc_trend(history) == "stable"

    def test_risk_indicators(self):
        history = [
            StudentAssessment(student_id="S001", student_name="张三",
                assessment_id="M1", subject="数学", grade="三年级",
                date="2024-01-01", total_score=45, max_score=100),
            StudentAssessment(student_id="S001", student_name="张三",
                assessment_id="M2", subject="数学", grade="三年级",
                date="2024-02-01", total_score=40, max_score=100),
        ]
        indicators = self.engine._calc_risk_indicators(history, 42.5)
        assert len(indicators) >= 1

    def test_parse_json_with_code_block(self):
        text = '```json\n{"key": "value"}\n```'
        result = self.engine._parse_json(text)
        assert result == {"key": "value"}

    def test_parse_json_plain(self):
        text = '{"key": "value"}'
        result = self.engine._parse_json(text)
        assert result == {"key": "value"}

    def test_parse_json_invalid(self):
        result = self.engine._parse_json("not json at all")
        assert result is None


# ══════════════════════════════════════════════════════════════════════════════
# Engine LLM 方法 mock 测试
# ══════════════════════════════════════════════════════════════════════════════

class TestAnalyticsEngineLLM:
    def _make_engine(self, mock_response: str):
        mlx = MagicMock()
        mlx.chat = AsyncMock(return_value=mock_response)
        return AnalyticsEngine(mlx=mlx)

    @pytest.mark.asyncio
    async def test_build_class_profile_empty(self):
        engine = self._make_engine("")
        result = await engine.build_class_profile("C1", "数学", "三年级", [])
        assert result.class_id == "C1"
        assert result.total_students == 0

    @pytest.mark.asyncio
    async def test_build_class_profile_with_data(self):
        engine = self._make_engine('{"weak_knowledge_points": [], "student_risk_levels": {}}')
        assessments = [
            StudentAssessment(
                student_id="S001", student_name="张三",
                assessment_id="M1", subject="数学", grade="三年级",
                date="2024-01-01", total_score=85, max_score=100,
                responses=[{"question_id": "计算", "correct": True, "student_answer": "42"}],
            ),
        ]
        result = await engine.build_class_profile("C1", "数学", "三年级", assessments)
        assert result.class_id == "C1"
        assert result.total_students == 1
        assert result.avg_score == 85.0

    @pytest.mark.asyncio
    async def test_build_student_profile_empty(self):
        engine = self._make_engine("")
        result = await engine.build_student_profile("S001", "数学", "三年级", [])
        assert result.student_id == "S001"

    @pytest.mark.asyncio
    async def test_build_student_profile_with_history(self):
        engine = self._make_engine(json.dumps({
            "overall_level": "struggling",
            "knowledge_mastery": {"计算": 40},
            "learning_trend": "declining",
            "risk_indicators": ["成绩下降"],
            "recommended_actions": ["加强练习"],
        }))
        history = [
            StudentAssessment(
                student_id="S001", student_name="张三",
                assessment_id="M1", subject="数学", grade="三年级",
                date="2024-01-01", total_score=60, max_score=100,
                scores={"计算": 12},
            ),
        ]
        result = await engine.build_student_profile("S001", "数学", "三年级", history)
        assert result.student_id == "S001"
        assert result.overall_level == "struggling"

    @pytest.mark.asyncio
    async def test_analyze_errors_empty(self):
        engine = self._make_engine("")
        result = await engine.analyze_errors("数学", "三年级", [])
        assert result == []

    @pytest.mark.asyncio
    async def test_analyze_errors_all_correct(self):
        engine = self._make_engine("")
        result = await engine.analyze_errors("数学", "三年级", [
            {"question_id": "q1", "correct": True, "student_answer": "42"},
        ])
        assert result == []

    @pytest.mark.asyncio
    async def test_analyze_errors_with_mistakes(self):
        engine = self._make_engine(json.dumps([{
            "error_id": "e1",
            "knowledge_point_id": "kp1",
            "error_type": "conceptual",
            "frequency": 2,
            "sample_responses": ["1/2"],
            "root_cause": "概念混淆",
            "remediation": "重讲概念",
        }]))
        responses = [
            {"question_id": "q1", "correct": False, "student_answer": "1/2"},
            {"question_id": "q2", "correct": False, "student_answer": "1/3"},
        ]
        result = await engine.analyze_errors("数学", "三年级", responses)
        assert len(result) == 1
        assert result[0].error_type == "conceptual"

    @pytest.mark.asyncio
    async def test_generate_remedial_plan_empty(self):
        engine = self._make_engine("")
        result = await engine.generate_remedial_plan("S001", "数学", "三年级", [])
        assert result.student_id == "S001"
        assert result.weak_points == []

    @pytest.mark.asyncio
    async def test_generate_remedial_plan_with_weak_points(self):
        engine = self._make_engine(json.dumps({
            "strategies": ["复习基础", "专项练习"],
            "timeline": "2周",
            "exercises": [{"topic": "分数", "type": "计算", "difficulty": "easy", "count": 5}],
            "estimated_duration": "2周",
        }))
        wp = WeakPoint(
            knowledge_point_id="kp1", knowledge_point_name="分数加减",
            error_rate=0.7, affected_students=["S001"],
        )
        result = await engine.generate_remedial_plan("S001", "数学", "三年级", [wp])
        assert result.student_id == "S001"
        assert len(result.weak_points) == 1
        assert result.timeline == "2周"

    @pytest.mark.asyncio
    async def test_generate_class_report(self):
        engine = self._make_engine("# 班级报告\n\n概述：整体良好。")
        profile = ClassProfile(
            class_id="C1", subject="数学", grade="三年级",
            period="2024-01", total_students=30, avg_score=78.5,
            score_distribution={"90-100": 5, "80-89": 10, "70-79": 8, "60-69": 4, "0-59": 3},
            weak_knowledge_points=[], strong_knowledge_points=["计算"],
            student_risk_levels={},
            generated_at="2024-01-01T00:00:00",
        )
        report = await engine.generate_class_report(profile)
        assert "班级报告" in report

    @pytest.mark.asyncio
    async def test_generate_class_report_fallback(self):
        mlx = MagicMock()
        mlx.chat = AsyncMock(side_effect=Exception("LLM down"))
        engine = AnalyticsEngine(mlx=mlx)
        profile = ClassProfile(
            class_id="C1", subject="数学", grade="三年级",
            period="2024-01", total_students=10, avg_score=75.0,
            score_distribution={"90-100": 2, "80-89": 3, "70-79": 2, "60-69": 2, "0-59": 1},
            weak_knowledge_points=[WeakPoint(
                knowledge_point_id="kp1", knowledge_point_name="分数",
                error_rate=0.5, affected_students=["S001"],
            )],
            strong_knowledge_points=[],
            student_risk_levels={"S001": "high"},
            generated_at="2024-01-01T00:00:00",
        )
        report = await engine.generate_class_report(profile)
        assert "班级学情报告" in report
        assert "分数" in report

    @pytest.mark.asyncio
    async def test_build_class_profile_llm_failure(self):
        mlx = MagicMock()
        mlx.chat = AsyncMock(side_effect=Exception("LLM down"))
        engine = AnalyticsEngine(mlx=mlx)
        assessments = [
            StudentAssessment(
                student_id="S001", student_name="张三",
                assessment_id="M1", subject="数学", grade="三年级",
                date="2024-01-01", total_score=85, max_score=100,
                responses=[{"question_id": "计算", "correct": True, "student_answer": "42"}],
            ),
        ]
        result = await engine.build_class_profile("C1", "数学", "三年级", assessments)
        assert result.class_id == "C1"
        assert result.avg_score == 85.0

    @pytest.mark.asyncio
    async def test_analyze_errors_llm_failure(self):
        mlx = MagicMock()
        mlx.chat = AsyncMock(side_effect=Exception("LLM down"))
        engine = AnalyticsEngine(mlx=mlx)
        responses = [{"question_id": "q1", "correct": False, "student_answer": "wrong"}]
        result = await engine.analyze_errors("数学", "三年级", responses)
        assert len(result) == 1
        assert result[0].error_id == "err-fallback"

    @pytest.mark.asyncio
    async def test_generate_remedial_plan_llm_failure(self):
        mlx = MagicMock()
        mlx.chat = AsyncMock(side_effect=Exception("LLM down"))
        engine = AnalyticsEngine(mlx=mlx)
        wp = WeakPoint(
            knowledge_point_id="kp1", knowledge_point_name="分数",
            error_rate=0.7, affected_students=["S001"],
        )
        result = await engine.generate_remedial_plan("S001", "数学", "三年级", [wp])
        assert len(result.weak_points) == 1
        assert len(result.strategies) >= 1
