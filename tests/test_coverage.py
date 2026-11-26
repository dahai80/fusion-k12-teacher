# Fusion-K12-Teacher full-coverage tests — CLI, AI, assessment, curriculum, subjects, content, personalization.

from __future__ import annotations

import pytest

from fusion_k12_teacher.ai_client import _HAS_FUSION_CORE, MLXClient
from fusion_k12_teacher.assessment import AssessmentEngine, GradingResult, StudentReport
from fusion_k12_teacher.content import ContentGenerator, Worksheet
from fusion_k12_teacher.curriculum import CurriculumEngine, LessonPlan, Quiz
from fusion_k12_teacher.personalization import LearningPath, PersonalizationEngine
from fusion_k12_teacher.subjects import SubjectExercise, SubjectExpert


# TEST-6: capture the prompt sent to the LLM and assert key content — a wrongly built prompt fails the test
def _capturing_mock(response_text: str):
    captured: list[str] = []

    async def chat(messages, temperature=0.7, max_tokens=4096, **kwargs):
        # join user message contents into the full prompt text
        parts = [m.get("content", "") for m in messages if m.get("role") == "user"]
        system = [m.get("content", "") for m in messages if m.get("role") == "system"]
        captured.append("\n".join(system + parts))
        return response_text

    return chat, captured


def _assert_prompt(captured: list[str], *must_contain: str) -> None:
    assert captured, "mock not called, prompt not captured — engine may not have sent a request"
    full = captured[-1]
    for token in must_contain:
        assert token in full, f"prompt missing required content {token!r}: {full[:200]}"

# ══════════════════════════════════════════════════════════════════════════════
# AI Client deep coverage
# ══════════════════════════════════════════════════════════════════════════════

class TestMLXClientDeep:
    # Test chat call with an explicit model.
    @pytest.mark.asyncio
    async def test_chat_with_model(self):
        client = MLXClient(model="test-model")
        assert client.model == "test-model"
        # raises when fusion-mlx is unavailable
        with pytest.raises(Exception):
            await client.chat([{"role": "user", "content": "hi"}])

    # Test _inner client initialization.
    def test_inner_client(self):
        client = MLXClient()
        assert (client._inner is not None) or (not _HAS_FUSION_CORE)

    # Test passing a custom base_url into _inner.
    def test_inner_client_custom_base_url(self):
        client = MLXClient(base_url="http://localhost:18000/v1")
        assert (client._inner is not None) or (not _HAS_FUSION_CORE)


# ══════════════════════════════════════════════════════════════════════════════
# Curriculum Engine deep coverage
# ══════════════════════════════════════════════════════════════════════════════

class TestCurriculumDeep:
    # Test all LessonPlan fields.
    def test_lesson_plan_all_fields(self):
        import time
        plan = LessonPlan(
            # i18n: user-facing
            id="lp_test", title="分数加减", subject="数学", grade="4",
            duration_minutes=40, objectives=["理解分数", "掌握加减"],
            materials=["课本", "练习册"],
            procedures=[{"step": 1, "activity": "导入"}],
            assessment="课堂提问", homework="练习册第5页",
            differentiation={"struggling": "简化题目"},
            created_at=time.strftime("%Y-%m-%d"),
        )
        d = plan.to_dict()
        assert d["id"] == "lp_test"
        # i18n: user-facing
        assert d["objectives"] == ["理解分数", "掌握加减"]

    # Test to_dict on an empty LessonPlan.
    def test_lesson_plan_to_dict_empty(self):
        plan = LessonPlan()
        d = plan.to_dict()
        # empty fields are filtered out
        assert "id" not in d or d["id"] == ""

    # Test Quiz with questions.
    def test_quiz_with_questions(self):
        quiz = Quiz(
            # i18n: user-facing
            title="单元测试", subject="数学", grade="3",
            questions=[{"q": "1+1=?", "type": "multiple_choice"}],
            total_points=100, time_limit_minutes=30,
        )
        assert quiz.total_points == 100
        assert len(quiz.questions) == 1

    # Test lesson plan generation with curriculum standards.
    @pytest.mark.asyncio
    async def test_generate_lesson_plan_with_standards(self):
        engine = CurriculumEngine()
        plan = await engine.generate_lesson_plan(
            # i18n: user-facing
            "数学", "3", "分数", duration=45, standards=["CCSS.MATH.3.NF"]
        )
        assert plan.grade == "3"

    # Test unit plan generation.
    @pytest.mark.asyncio
    async def test_generate_unit_plan(self):
        engine = CurriculumEngine()
        # i18n: user-facing
        result = await engine.generate_unit_plan("数学", "3", "分数运算", weeks=4)
        assert isinstance(result, dict)

    # Test JSON parsing.
    def test_parse_json_valid(self):
        engine = CurriculumEngine()
        result = engine._parse_json('{"key": "value"}')
        assert result == {"key": "value"}

    # Test JSON parsing inside a code block.
    def test_parse_json_codeblock(self):
        engine = CurriculumEngine()
        result = engine._parse_json('```json\n{"a": 1}\n```')
        assert result == {"a": 1}

    # Test invalid JSON parsing.
    def test_parse_json_invalid(self):
        engine = CurriculumEngine()
        result = engine._parse_json("not json")
        assert result is None


# ══════════════════════════════════════════════════════════════════════════════
# Assessment Engine deep coverage
# ══════════════════════════════════════════════════════════════════════════════

class TestAssessmentDeep:
    # Test all GradingResult fields.
    def test_grading_result_all_fields(self):
        result = GradingResult(
            score=85, total=100, percentage=85.0, feedback="Good work!",
            # i18n: user-facing
            strengths=["语法正确", "结构清晰"],
            improvements=["增加细节"],
            rubric_scores={"内容": 40, "语言": 45},
        )
        assert result.score == 85
        # i18n: user-facing
        assert result.strengths == ["语法正确", "结构清晰"]
        assert result.rubric_scores["内容"] == 40

    # Test all StudentReport fields.
    def test_student_report_all_fields(self):
        report = StudentReport(
            # i18n: user-facing
            student_name="张三", subject="数学", grade="3",
            period="2026春", overall_score=90.0,
            skills={"运算": 95, "几何": 85},
            strengths=["计算能力强"],
            areas_to_improve=["应用题"],
            teacher_notes="继续努力！",
        )
        # i18n: user-facing
        assert report.skills["运算"] == 95
        assert report.teacher_notes == "继续努力！"

    # Test essay grading with a rubric.
    @pytest.mark.asyncio
    async def test_grade_essay_with_rubric(self):
        engine = AssessmentEngine()
        result = await engine.grade_essay(
            # i18n: user-facing
            "今天天气真好。",
            rubric={"内容": 50, "语言": 50},
        )
        assert result.total == 100

    # Test math grading with a reference answer.
    @pytest.mark.asyncio
    async def test_grade_math_with_solution(self):
        engine = AssessmentEngine()
        result = await engine.grade_math("2+2=?", "4", "4")
        assert result.total == 10

    # Test term report generation with learning history.
    @pytest.mark.asyncio
    async def test_generate_report_with_history(self):
        engine = AssessmentEngine()
        report = await engine.generate_report(
            # i18n: user-facing
            "张三", "数学", "3",
            [{"score": 90, "date": "2026-01"}, {"score": 85, "date": "2026-02"}],
        )
        # i18n: user-facing
        assert report.student_name == "张三"

    # Test rubric generation with custom criteria.
    @pytest.mark.asyncio
    async def test_generate_rubric_with_criteria(self):
        engine = AssessmentEngine()
        result = await engine.generate_rubric(
            # i18n: user-facing
            "写作", "4", criteria=["内容", "结构", "语法", "创意"]
        )
        assert isinstance(result, dict)

    # Test invalid JSON.
    def test_parse_json_invalid(self):
        engine = AssessmentEngine()
        assert engine._parse_json("bad") is None


# ══════════════════════════════════════════════════════════════════════════════
# Subject Expert deep coverage
# ══════════════════════════════════════════════════════════════════════════════

class TestSubjectDeep:
    # Test all SubjectExercise fields.
    def test_exercise_all_fields(self):
        ex = SubjectExercise(
            # i18n: user-facing
            question="1+1=?", difficulty="easy", subject="数学", grade="1",
            hints=["数一数"], answer="2", explanation="1个加1个等于2个",
            topic="加法", skills=["计数", "加法运算"],
        )
        # i18n: user-facing
        assert ex.hints == ["数一数"]
        assert ex.skills == ["计数", "加法运算"]

    @pytest.mark.asyncio
    async def test_explain_concept(self):
        # TEST-2: inject a mock chat and strictly assert the parsed real fields (success-path coverage, not isinstance fallback)
        expert = SubjectExpert()
        async def mock_chat(messages, temperature=0.7, max_tokens=4096):
            # i18n: user-facing
            return '{"simple_explanation": "植物利用阳光制造养分", "example": "树叶在阳光下变绿", "visualization": "画阳光箭头照向叶子", "common_misconceptions": ["植物吃土"], "extension": "光合作用与呼吸作用的关系"}'
        expert.mlx.chat = mock_chat
        # i18n: user-facing
        result = await expert.explain_concept("科学", "5", "光合作用")
        assert isinstance(result, dict)
        assert result.get("simple_explanation")
        assert "error" not in result

    @pytest.mark.asyncio
    async def test_generate_exercise_with_difficulty(self):
        # TEST-2: mock chat + strictly assert real parsing of question/answer/difficulty
        expert = SubjectExpert()
        async def mock_chat(messages, temperature=0.7, max_tokens=4096):
            # i18n: user-facing
            return '{"question": "3×4=?", "hints": ["想3个4相加"], "answer": "12", "explanation": "3乘4等于12", "skills": ["乘法"]}'
        expert.mlx.chat = mock_chat
        # i18n: user-facing
        ex = await expert.generate_exercise("数学", "3", "乘法", difficulty="hard")
        assert ex.topic == "乘法"
        assert ex.question == "3×4=?"
        assert ex.answer == "12"
        assert ex.difficulty == "hard"
        # i18n: user-facing
        assert "失败" not in ex.question

    @pytest.mark.asyncio
    async def test_stem_project_with_duration(self):
        # TEST-2: mock chat + strictly assert real parsing of title/driving_question
        expert = SubjectExpert()
        async def mock_chat(messages, temperature=0.7, max_tokens=4096):
            # i18n: user-facing
            return '{"title": "水循环探究", "driving_question": "水去哪了", "objectives": ["理解蒸发"], "materials": ["杯子"], "procedure": ["观察"], "expected_outcomes": ["能画出循环图"], "rubric": "参与度评分"}'
        expert.mlx.chat = mock_chat
        # i18n: user-facing
        result = await expert.stem_project("5", "水循环", duration="4课时")
        assert isinstance(result, dict)
        # i18n: user-facing
        assert result.get("title") == "水循环探究"
        assert result.get("driving_question")
        assert "error" not in result

    @pytest.mark.asyncio
    async def test_language_activity(self):
        # TEST-2: mock chat + strictly assert real parsing of title/objective
        expert = SubjectExpert()
        async def mock_chat(messages, temperature=0.7, max_tokens=4096):
            # i18n: user-facing
            return '{"title": "动物听力游戏", "objective": "辨动物叫声", "materials": ["音频"], "procedure": ["听辨"], "differentiation": {"beginner": "看图选", "intermediate": "听音选", "advanced": "听写"}}'
        expert.mlx.chat = mock_chat
        # i18n: user-facing
        result = await expert.language_activity("3", "英语", "听力", "动物")
        assert isinstance(result, dict)
        # i18n: user-facing
        assert result.get("title") == "动物听力游戏"
        assert result.get("objective")
        assert "error" not in result

    # Test invalid JSON.
    def test_parse_json_invalid(self):
        expert = SubjectExpert()
        assert expert._parse_json("bad") is None


# ══════════════════════════════════════════════════════════════════════════════
# Personalization Engine deep coverage
# ══════════════════════════════════════════════════════════════════════════════

class TestPersonalizationDeep:
    # Test all LearningPath fields.
    def test_learning_path_all_fields(self):
        path = LearningPath(
            # i18n: user-facing
            student_id="s1", grade="3", subject="数学",
            units=[{"title": "分数入门"}],
            estimated_duration="4周",
            prerequisites=["整数运算"],
            goals=["理解分数概念"],
        )
        # i18n: user-facing
        assert path.units[0]["title"] == "分数入门"
        assert path.prerequisites == ["整数运算"]

    # Test learning path creation.
    @pytest.mark.asyncio
    async def test_create_learning_path(self):
        engine = PersonalizationEngine()
        # i18n: user-facing
        path = await engine.create_learning_path("张三", "3", "数学", "掌握分数")
        assert path.student_id == "张三"

    # Test skill diagnosis.
    @pytest.mark.asyncio
    async def test_diagnose_skills(self):
        engine = PersonalizationEngine()
        # i18n: user-facing
        result = await engine.diagnose_skills("数学", "3", [])
        assert isinstance(result, dict)

    # Test resource recommendation.
    @pytest.mark.asyncio
    async def test_recommend_resources(self):
        engine = PersonalizationEngine()
        # i18n: user-facing
        result = await engine.recommend_resources("张三", "3", "数学", "分数")
        assert isinstance(result, dict)

    # Test invalid JSON.
    def test_parse_json_invalid(self):
        engine = PersonalizationEngine()
        assert engine._parse_json("bad") is None


# ══════════════════════════════════════════════════════════════════════════════
# Content Generator deep coverage
# ══════════════════════════════════════════════════════════════════════════════

class TestContentDeep:
    # Test all Worksheet fields.
    def test_worksheet_all_fields(self):
        ws = Worksheet(
            # i18n: user-facing
            title="分数练习", subject="数学", grade="3",
            sections=[{"title": "选择题", "questions": [{"q": "1/2+1/2=?"}]}],
            answer_key="1", instructions="认真答题",
        )
        # i18n: user-facing
        assert ws.sections[0]["title"] == "选择题"
        assert ws.instructions == "认真答题"

    # Test worksheet generation.
    @pytest.mark.asyncio
    async def test_generate_worksheet(self):
        gen = ContentGenerator()
        # i18n: user-facing
        ws = await gen.generate_worksheet("数学", "3", "分数", num_questions=5)
        assert ws.subject == "数学"

    # Test flashcard generation.
    @pytest.mark.asyncio
    async def test_generate_flashcards(self):
        gen = ContentGenerator()
        # i18n: user-facing
        cards = await gen.generate_flashcards("数学", "3", "分数", count=5)
        assert isinstance(cards, list)

    # Test lesson slides generation.
    @pytest.mark.asyncio
    async def test_generate_lesson_slides(self):
        gen = ContentGenerator()
        # i18n: user-facing
        slides = await gen.generate_lesson_slides("数学", "3", "分数", num_slides=5)
        assert isinstance(slides, list)

    # Test educational game generation.
    @pytest.mark.asyncio
    async def test_generate_educational_game(self):
        gen = ContentGenerator()
        # i18n: user-facing
        result = await gen.generate_educational_game("数学", "3", "分数", game_type="board")
        assert isinstance(result, dict)

    # Test parent communication letter generation.
    @pytest.mark.asyncio
    async def test_generate_parent_communication(self):
        gen = ContentGenerator()
        # i18n: user-facing
        result = await gen.generate_parent_communication("张三", "3", "数学", "分数")
        assert isinstance(result, str)

    # Test invalid JSON.
    def test_parse_json_invalid(self):
        gen = ContentGenerator()
        assert gen._parse_json("bad") is None


# ══════════════════════════════════════════════════════════════════════════════
# CLI tests
# ══════════════════════════════════════════════════════════════════════════════

class TestCLICoverage:
    # TEST-7: no longer blindly accept exit_code in (0,1) — that conflates success with engine degradation and masks real failures.
    #
    #         - exit_code==2 is a Click usage error/argument parsing failure, never accepted;
    #         - result.exception that is not SystemExit means an uncaught crash, never accepted
    #           (Click's ClickException exiting via SystemExit(n) is normal graceful degradation, acceptable);
    #         - when the backend (fusion-mlx + chat model) is online, assert the success path (exit 0 + success_marker in output);
    #         - when the backend is unavailable, assert graceful degradation (exit 1, no crash) with non-empty output (CLI gave feedback).
    @staticmethod
    def _assert_cli_not_crashed(result, success_marker: str = ""):
        assert result.exit_code != 2, f"CLI usage error (exit 2): {result.output}"
        # Click's ClickException -> SystemExit(1) is normal degradation, not a crash;
        # only non-SystemExit exceptions are real crashes (unhandled).
        if result.exception is not None and not isinstance(result.exception, SystemExit):
            raise AssertionError(f"CLI uncaught exception: {result.exception!r}")
        if result.exit_code == 0:
            assert success_marker in result.output, (
                f"success path but marker missing {success_marker!r}: {result.output[:300]}"
            )
        else:
            assert result.output.strip(), f"failure path produced no output: exit={result.exit_code}"

    # Test CLI importability.
    def test_cli_import(self):
        from fusion_k12_teacher import cli
        assert cli is not None
        assert cli.main is not None

    # Test CLI help output.
    def test_cli_help(self):
        from click.testing import CliRunner

        from fusion_k12_teacher.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Fusion-K12-Teacher" in result.output

    # Test CLI version output.
    def test_cli_version(self):
        from click.testing import CliRunner

        from fusion_k12_teacher.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0

    # Test subcommand help.
    def test_cli_lesson_plan_help(self):
        from click.testing import CliRunner

        from fusion_k12_teacher.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["lesson", "plan", "--help"])
        assert result.exit_code == 0

    # Test quiz subcommand help.
    def test_cli_lesson_quiz_help(self):
        from click.testing import CliRunner

        from fusion_k12_teacher.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["lesson", "quiz", "--help"])
        assert result.exit_code == 0

    # Test assess essay help.
    def test_cli_assess_essay_help(self):
        from click.testing import CliRunner

        from fusion_k12_teacher.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["assess", "essay", "--help"])
        assert result.exit_code == 0

    # Test subject explain help.
    def test_cli_subject_explain_help(self):
        from click.testing import CliRunner

        from fusion_k12_teacher.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["subject", "explain", "--help"])
        assert result.exit_code == 0

    # Test personalize path help.
    def test_cli_personalize_path_help(self):
        from click.testing import CliRunner

        from fusion_k12_teacher.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["personalize", "path", "--help"])
        assert result.exit_code == 0

    # Test content worksheet help.
    def test_cli_content_worksheet_help(self):
        from click.testing import CliRunner

        from fusion_k12_teacher.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["content", "worksheet", "--help"])
        assert result.exit_code == 0

    # Test lesson plan command execution.
    def test_cli_lesson_plan_run(self, tmp_path):
        from click.testing import CliRunner

        from fusion_k12_teacher.cli import cli
        runner = CliRunner()
        # i18n: user-facing
        result = runner.invoke(cli, ["lesson", "plan", "数学", "3", "分数"])
        # TEST-7: distinguish success/degradation, reject usage errors and crashes; success must show the 📚 marker
        self._assert_cli_not_crashed(result, "📚")

    # Test lesson quiz command execution.
    def test_cli_lesson_quiz_run(self, tmp_path):
        from click.testing import CliRunner

        from fusion_k12_teacher.cli import cli
        runner = CliRunner()
        # i18n: user-facing
        result = runner.invoke(cli, ["lesson", "quiz", "数学", "3", "分数"])
        # TEST-7: success must show the 📝 marker
        self._assert_cli_not_crashed(result, "📝")

    # Test subject explain command execution.
    def test_cli_subject_explain_run(self, tmp_path):
        from click.testing import CliRunner

        from fusion_k12_teacher.cli import cli
        runner = CliRunner()
        # i18n: user-facing
        result = runner.invoke(cli, ["subject", "explain", "科学", "5", "光合作用"])
        # TEST-7: success must show the 📖 marker
        self._assert_cli_not_crashed(result, "📖")

    # Test content worksheet command execution.
    def test_cli_content_worksheet_run(self, tmp_path):
        from click.testing import CliRunner

        from fusion_k12_teacher.cli import cli
        runner = CliRunner()
        # i18n: user-facing
        result = runner.invoke(cli, ["content", "worksheet", "数学", "3", "分数"])
        # TEST-7: success must show the 📄 marker
        self._assert_cli_not_crashed(result, "📄")


# ══════════════════════════════════════════════════════════════════════════════
# Mock tests — simulate fusion-mlx success responses, covering success paths
# ══════════════════════════════════════════════════════════════════════════════

# Simulate fusion-mlx success responses, covering success paths inside try blocks.
class TestMockSuccess:

    # Test curriculum JSON parsing success path.
    @pytest.mark.asyncio
    async def test_curriculum_parse_json_success(self):
        engine = CurriculumEngine()
        # TEST-6: capture the prompt and assert subject/grade/topic key content
        chat, captured = _capturing_mock(
            # i18n: user-facing
            '{"title": "分数", "objectives": ["理解分数"], "materials": ["课本"], "procedures": [{"step": 1, "activity": "导入"}], "assessment": "提问", "homework": "练习"}'
        )
        engine.mlx.chat = chat
        # i18n: user-facing
        plan = await engine.generate_lesson_plan("数学", "3", "分数")
        _assert_prompt(captured, "数学", "3", "分数")
        assert plan.title == "分数"
        assert "理解分数" in plan.objectives

    # Test the fallback when JSON parsing fails.
    @pytest.mark.asyncio
    async def test_curriculum_parse_json_none(self):
        engine = CurriculumEngine()
        async def mock_chat(messages, temperature=0.7, max_tokens=4096):
            return "invalid json"
        engine.mlx.chat = mock_chat
        # i18n: user-facing
        plan = await engine.generate_lesson_plan("数学", "3", "分数")
        assert plan.title == "分数"
        assert plan.grade == "3"

    # Test quiz generation success path.
    @pytest.mark.asyncio
    async def test_curriculum_quiz_success(self):
        engine = CurriculumEngine()
        chat, captured = _capturing_mock(
            '[{"question": "1+1=?", "type": "multiple_choice", "options": ["1","2","3"], "answer": "2", "points": 5, "difficulty": "easy"}]'
        )
        engine.mlx.chat = chat
        # i18n: user-facing
        quiz = await engine.generate_quiz("数学", "3", "加法", num_questions=1)
        _assert_prompt(captured, "数学", "3", "加法")
        assert len(quiz.questions) == 1

    # Test essay grading success path.
    @pytest.mark.asyncio
    async def test_assessment_essay_success(self):
        engine = AssessmentEngine()
        chat, captured = _capturing_mock(
            # i18n: user-facing
            '{"score": 85, "total": 100, "feedback": "Good", "strengths": ["清晰"], "improvements": ["细节"], "rubric_scores": {"内容": 40}}'
        )
        engine.mlx.chat = chat
        result = await engine.grade_essay("test essay")
        _assert_prompt(captured, "test essay")
        assert result.score == 85
        # i18n: user-facing
        assert "清晰" in result.strengths

    # Test math grading success path.
    @pytest.mark.asyncio
    async def test_assessment_math_success(self):
        engine = AssessmentEngine()
        chat, captured = _capturing_mock(
            # i18n: user-facing
            '{"score": 10, "total": 10, "correct": true, "feedback": "正确", "mistakes": []}'
        )
        engine.mlx.chat = chat
        result = await engine.grade_math("2+2=?", "4", "4")
        _assert_prompt(captured, "2+2=?", "4")
        assert result.score == 10

    # Test report generation success path.
    @pytest.mark.asyncio
    async def test_assessment_report_success(self):
        engine = AssessmentEngine()
        chat, captured = _capturing_mock(
            # i18n: user-facing
            '{"overall_score": 90, "skills": {"运算": 95}, "strengths": ["计算"], "areas_to_improve": ["应用"], "teacher_notes": "好"}'
        )
        engine.mlx.chat = chat
        # i18n: user-facing
        report = await engine.generate_report("张三", "数学", "3", [])
        _assert_prompt(captured, "张三", "数学", "3")
        assert report.overall_score == 90
        # i18n: user-facing
        assert "计算" in report.strengths

    # Test concept explanation success path.
    @pytest.mark.asyncio
    async def test_subject_explain_success(self):
        expert = SubjectExpert()
        chat, captured = _capturing_mock(
            # i18n: user-facing
            '{"simple_explanation": "光合作用就是植物用阳光制造食物", "example": "阳光照在叶子上", "common_misconceptions": ["植物不需要阳光"]}'
        )
        expert.mlx.chat = chat
        # i18n: user-facing
        result = await expert.explain_concept("科学", "5", "光合作用")
        _assert_prompt(captured, "科学", "5", "光合作用")
        assert "光合作用" in result.get("simple_explanation", "")

    # Test learning path creation success path.
    @pytest.mark.asyncio
    async def test_personalization_path_success(self):
        engine = PersonalizationEngine()
        chat, captured = _capturing_mock(
            # i18n: user-facing
            '{"goals": ["掌握分数"], "units": [{"title": "分数入门", "duration": "2周", "activities": ["练习"], "mastery_criteria": "80%"}], "prerequisites": ["整数"], "estimated_duration": "4周"}'
        )
        engine.mlx.chat = chat
        # i18n: user-facing
        path = await engine.create_learning_path("张三", "3", "数学", "掌握分数")
        _assert_prompt(captured, "张三", "3", "数学", "掌握分数")
        assert "掌握分数" in path.goals
        assert len(path.units) >= 1

    # Test worksheet generation success path.
    @pytest.mark.asyncio
    async def test_content_worksheet_success(self):
        gen = ContentGenerator()
        chat, captured = _capturing_mock(
            # i18n: user-facing
            '{"title": "分数练习", "instructions": "认真答题", "sections": [{"title": "选择题", "questions": [{"question": "1/2=?", "type": "choice", "points": 5}]}], "answer_key": "0.5"}'
        )
        gen.mlx.chat = chat
        # i18n: user-facing
        ws = await gen.generate_worksheet("数学", "3", "分数", num_questions=1)
        _assert_prompt(captured, "数学", "3", "分数")
        assert ws.title == "分数练习"
        assert len(ws.sections) >= 1

    # Test flashcard generation success path.
    @pytest.mark.asyncio
    async def test_content_flashcards_success(self):
        gen = ContentGenerator()
        chat, captured = _capturing_mock(
            # i18n: user-facing
            '[{"front": "1/2", "back": "0.5", "hint": "一半"}, {"front": "1/4", "back": "0.25", "hint": "四分之一"}]'
        )
        gen.mlx.chat = chat
        # i18n: user-facing
        cards = await gen.generate_flashcards("数学", "3", "分数", count=2)
        _assert_prompt(captured, "数学", "3", "分数")
        assert len(cards) == 2

    # Test lesson slides generation success path.
    @pytest.mark.asyncio
    async def test_content_slides_success(self):
        gen = ContentGenerator()
        chat, captured = _capturing_mock(
            # i18n: user-facing
            '[{"slide_number": 1, "title": "引言", "content": "什么是分数", "teacher_notes": "举例说明"}]'
        )
        gen.mlx.chat = chat
        # i18n: user-facing
        slides = await gen.generate_lesson_slides("数学", "3", "分数", num_slides=1)
        _assert_prompt(captured, "数学", "3", "分数")
        assert len(slides) == 1

    # Test educational game generation success path.
    @pytest.mark.asyncio
    async def test_content_game_success(self):
        gen = ContentGenerator()
        chat, captured = _capturing_mock(
            # i18n: user-facing
            '{"title": "分数大冒险", "type": "board", "objective": "掌握分数", "rules": ["掷骰子前进"], "materials": ["骰子"], "duration": "15分钟", "setup": "打印棋盘", "variations": ["难度升级"], "debrief": "学到了什么"}'
        )
        gen.mlx.chat = chat
        # i18n: user-facing
        result = await gen.generate_educational_game("数学", "3", "分数")
        _assert_prompt(captured, "数学", "3", "分数")
        assert result["title"] == "分数大冒险"

    # Test skill diagnosis success path.
    @pytest.mark.asyncio
    async def test_diagnose_skills_success(self):
        engine = PersonalizationEngine()
        chat, captured = _capturing_mock(
            # i18n: user-facing
            '{"mastered_skills": ["加法"], "developing_skills": ["减法"], "needs_support": ["乘法"], "overall_level": "developing", "recommendations": ["多练习"]}'
        )
        engine.mlx.chat = chat
        # i18n: user-facing
        result = await engine.diagnose_skills("数学", "3", [])
        _assert_prompt(captured, "数学", "3")
        assert result["overall_level"] == "developing"

    # Test resource recommendation success path.
    @pytest.mark.asyncio
    async def test_recommend_resources_success(self):
        engine = PersonalizationEngine()
        chat, captured = _capturing_mock(
            # i18n: user-facing
            '{"resources": [{"type": "视频", "title": "分数入门", "description": "动画教学", "duration": "5分钟", "difficulty": "easy"}], "practice_plan": "每天10题", "parent_tips": "鼓励孩子"}'
        )
        engine.mlx.chat = chat
        # i18n: user-facing
        result = await engine.recommend_resources("张三", "3", "数学", "分数")
        # prompt contains grade/student/weakness, not subject
        # i18n: user-facing
        _assert_prompt(captured, "张三", "3", "分数")
        assert len(result["resources"]) >= 1

    # Test rubric generation success path.
    @pytest.mark.asyncio
    async def test_rubric_success(self):
        engine = AssessmentEngine()
        chat, captured = _capturing_mock(
            # i18n: user-facing
            '{"criteria": [{"name": "内容", "points": 40, "levels": {"优秀": "内容丰富", "良好": "基本完整"}}]}'
        )
        engine.mlx.chat = chat
        # i18n: user-facing
        result = await engine.generate_rubric("作文", "5")
        _assert_prompt(captured, "作文", "5")
        assert "criteria" in result

    # Test AI client _inner initialization.
    @pytest.mark.asyncio
    async def test_ai_client_chat_success(self):
        from fusion_k12_teacher.ai_client import _HAS_FUSION_CORE, MLXClient
        client = MLXClient(model="test")
        assert (client._inner is not None) or (not _HAS_FUSION_CORE)
        # test chat failure (fusion-mlx unavailable)
        with pytest.raises(Exception):
            await client.chat([{"role": "user", "content": "hi"}])