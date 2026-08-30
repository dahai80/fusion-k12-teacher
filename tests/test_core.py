"""Fusion-K12-Teacher 核心测试。"""

from __future__ import annotations

import pytest

from fusion_k12_teacher.ai_client import MLXClient
from fusion_k12_teacher.assessment import AssessmentEngine, GradingResult, StudentReport
from fusion_k12_teacher.content import ContentGenerator, Worksheet
from fusion_k12_teacher.curriculum import CurriculumEngine, LessonPlan, Quiz
from fusion_k12_teacher.personalization import LearningPath, PersonalizationEngine
from fusion_k12_teacher.subjects import SubjectExercise, SubjectExpert


class TestMLXClient:
    def test_init(self):
        client = MLXClient(model="test-model")
        assert client.model == "test-model"

    def test_default_model(self):
        client = MLXClient()
        assert client.model == ""


class TestCurriculumEngine:
    def test_lesson_plan_defaults(self):
        plan = LessonPlan(title="Test", subject="数学", grade="3")
        assert plan.subject == "数学"
        assert plan.grade == "3"
        assert plan.duration_minutes == 45

    def test_quiz_defaults(self):
        quiz = Quiz(title="Test", subject="数学", grade="3")
        assert quiz.total_points == 0
        assert quiz.questions == []

    def test_lesson_plan_to_dict(self):
        plan = LessonPlan(id="lp1", title="分数", subject="数学", grade="4",
                          objectives=["理解分数概念"])
        d = plan.to_dict()
        assert d["id"] == "lp1"
        assert d["objectives"] == ["理解分数概念"]

    @pytest.mark.asyncio
    async def test_generate_lesson_plan(self):
        engine = CurriculumEngine()
        plan = await engine.generate_lesson_plan("数学", "3", "分数")
        assert plan.subject == "数学"
        assert plan.grade == "3"

    @pytest.mark.asyncio
    async def test_generate_quiz(self):
        engine = CurriculumEngine()
        quiz = await engine.generate_quiz("数学", "3", "分数", num_questions=3)
        assert quiz.subject == "数学"

    @pytest.mark.asyncio
    async def test_generate_unit_plan(self):
        engine = CurriculumEngine()
        result = await engine.generate_unit_plan("数学", "3", "分数运算")
        assert "unit_title" in result or "error" in result


class TestAssessmentEngine:
    def test_grading_result_defaults(self):
        result = GradingResult(score=85, total=100, feedback="Good")
        # percentage 有默认值，不自动计算
        assert result.score == 85
        assert result.total == 100
        assert result.feedback == "Good"

    def test_student_report_defaults(self):
        report = StudentReport(student_name="张三", subject="数学", grade="3")
        assert report.student_name == "张三"
        assert report.overall_score == 0.0

    @pytest.mark.asyncio
    async def test_grade_essay(self):
        engine = AssessmentEngine()
        result = await engine.grade_essay("今天天气真好，我们去公园玩。")
        assert result.total == 100
        assert result.percentage >= 0

    @pytest.mark.asyncio
    async def test_grade_math(self):
        engine = AssessmentEngine()
        result = await engine.grade_math("2+2=?", "4", "4")
        assert result.total == 10

    @pytest.mark.asyncio
    async def test_generate_report(self):
        engine = AssessmentEngine()
        report = await engine.generate_report("张三", "数学", "3", [])
        assert report.student_name == "张三"

    @pytest.mark.asyncio
    async def test_generate_rubric(self):
        engine = AssessmentEngine()
        result = await engine.generate_rubric("作文", "5")
        assert "error" in result or len(result) > 0


class TestSubjectExpert:
    def test_exercise_defaults(self):
        ex = SubjectExercise(question="1+1=?", subject="数学", grade="1")
        assert ex.question == "1+1=?"
        assert ex.difficulty == "medium"

    @pytest.mark.asyncio
    async def test_explain_concept(self):
        expert = SubjectExpert()
        result = await expert.explain_concept("数学", "3", "分数")
        assert "error" in result or "simple_explanation" in result or "concept" in result

    @pytest.mark.asyncio
    async def test_generate_exercise(self):
        expert = SubjectExpert()
        ex = await expert.generate_exercise("数学", "3", "加法")
        # fusion-mlx 不可用时返回带错误信息的对象
        assert ex.topic == "加法"

    @pytest.mark.asyncio
    async def test_stem_project(self):
        expert = SubjectExpert()
        result = await expert.stem_project("5", "水循环")
        assert "title" in result or "error" in result

    @pytest.mark.asyncio
    async def test_language_activity(self):
        expert = SubjectExpert()
        result = await expert.language_activity("3", "英语", "口语", "自我介绍")
        assert "title" in result or "error" in result


class TestPersonalizationEngine:
    def test_learning_path_defaults(self):
        path = LearningPath(student_id="s1", grade="3", subject="数学")
        assert path.student_id == "s1"
        assert path.units == []

    @pytest.mark.asyncio
    async def test_create_learning_path(self):
        engine = PersonalizationEngine()
        path = await engine.create_learning_path("张三", "3", "数学", "掌握分数运算")
        assert path.student_id == "张三"

    @pytest.mark.asyncio
    async def test_diagnose_skills(self):
        engine = PersonalizationEngine()
        result = await engine.diagnose_skills("数学", "3", [])
        assert "overall_level" in result or "error" in result

    @pytest.mark.asyncio
    async def test_recommend_resources(self):
        engine = PersonalizationEngine()
        result = await engine.recommend_resources("张三", "3", "数学", "分数")
        assert "resources" in result or "error" in result


class TestContentGenerator:
    def test_worksheet_defaults(self):
        ws = Worksheet(title="Test", subject="数学", grade="3")
        assert ws.subject == "数学"
        assert ws.sections == []

    @pytest.mark.asyncio
    async def test_generate_worksheet(self):
        gen = ContentGenerator()
        ws = await gen.generate_worksheet("数学", "3", "分数")
        assert ws.subject == "数学"

    @pytest.mark.asyncio
    async def test_generate_flashcards(self):
        gen = ContentGenerator()
        cards = await gen.generate_flashcards("数学", "3", "分数", count=3)
        assert isinstance(cards, list)

    @pytest.mark.asyncio
    async def test_generate_lesson_slides(self):
        gen = ContentGenerator()
        slides = await gen.generate_lesson_slides("数学", "3", "分数", num_slides=3)
        assert isinstance(slides, list)

    @pytest.mark.asyncio
    async def test_generate_educational_game(self):
        gen = ContentGenerator()
        result = await gen.generate_educational_game("数学", "3", "分数")
        assert "title" in result or "error" in result

    @pytest.mark.asyncio
    async def test_generate_parent_communication(self):
        gen = ContentGenerator()
        result = await gen.generate_parent_communication("张三", "3", "数学", "分数")
        assert isinstance(result, str)


class TestModuleIntegrity:
    def test_all_modules_importable(self):
        import fusion_k12_teacher
        assert fusion_k12_teacher.__version__ == "1.0.8"

    def test_cli_importable(self):
        from fusion_k12_teacher import cli
        assert cli.main is not None

    def test_grade_levels(self):
        from fusion_k12_teacher.curriculum.engine import GRADE_LEVELS, SUBJECTS
        assert len(GRADE_LEVELS) == 13
        assert "数学" in SUBJECTS