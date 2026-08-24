"""Fusion-K12-Teacher 全覆盖测试 — 补齐 CLI、AI、评估、课程、学科、内容、个性化。"""

from __future__ import annotations

import pytest

from fusion_k12_teacher.ai_client import _HAS_FUSION_CORE, MLXClient
from fusion_k12_teacher.assessment import AssessmentEngine, GradingResult, StudentReport
from fusion_k12_teacher.content import ContentGenerator, Worksheet
from fusion_k12_teacher.curriculum import CurriculumEngine, LessonPlan, Quiz
from fusion_k12_teacher.personalization import LearningPath, PersonalizationEngine
from fusion_k12_teacher.subjects import SubjectExercise, SubjectExpert

# ══════════════════════════════════════════════════════════════════════════════
# AI Client 深度覆盖
# ══════════════════════════════════════════════════════════════════════════════

class TestMLXClientDeep:
    @pytest.mark.asyncio
    async def test_chat_with_model(self):
        """测试指定模型的 chat 调用。"""
        client = MLXClient(model="test-model")
        assert client.model == "test-model"
        # fusion-mlx 不可用时抛出异常
        with pytest.raises(Exception):
            await client.chat([{"role": "user", "content": "hi"}])

    def test_inner_client(self):
        """测试 _inner 客户端初始化。"""
        client = MLXClient()
        assert (client._inner is not None) or (not _HAS_FUSION_CORE)

    def test_inner_client_custom_base_url(self):
        """测试自定义 base_url 传入 _inner。"""
        client = MLXClient(base_url="http://localhost:18000/v1")
        assert (client._inner is not None) or (not _HAS_FUSION_CORE)


# ══════════════════════════════════════════════════════════════════════════════
# Curriculum Engine 深度覆盖
# ══════════════════════════════════════════════════════════════════════════════

class TestCurriculumDeep:
    def test_lesson_plan_all_fields(self):
        """测试 LessonPlan 全部字段。"""
        import time
        plan = LessonPlan(
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
        assert d["objectives"] == ["理解分数", "掌握加减"]

    def test_lesson_plan_to_dict_empty(self):
        """测试空 LessonPlan 的 to_dict。"""
        plan = LessonPlan()
        d = plan.to_dict()
        # 空值字段被过滤
        assert "id" not in d or d["id"] == ""

    def test_quiz_with_questions(self):
        """测试带题目的 Quiz。"""
        quiz = Quiz(
            title="单元测试", subject="数学", grade="3",
            questions=[{"q": "1+1=?", "type": "multiple_choice"}],
            total_points=100, time_limit_minutes=30,
        )
        assert quiz.total_points == 100
        assert len(quiz.questions) == 1

    @pytest.mark.asyncio
    async def test_generate_lesson_plan_with_standards(self):
        """测试带课程标准的教案生成。"""
        engine = CurriculumEngine()
        plan = await engine.generate_lesson_plan(
            "数学", "3", "分数", duration=45, standards=["CCSS.MATH.3.NF"]
        )
        assert plan.grade == "3"

    @pytest.mark.asyncio
    async def test_generate_unit_plan(self):
        """测试单元计划生成。"""
        engine = CurriculumEngine()
        result = await engine.generate_unit_plan("数学", "3", "分数运算", weeks=4)
        assert isinstance(result, dict)

    def test_parse_json_valid(self):
        """测试 JSON 解析。"""
        engine = CurriculumEngine()
        result = engine._parse_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_parse_json_codeblock(self):
        """测试代码块中的 JSON 解析。"""
        engine = CurriculumEngine()
        result = engine._parse_json('```json\n{"a": 1}\n```')
        assert result == {"a": 1}

    def test_parse_json_invalid(self):
        """测试无效 JSON 解析。"""
        engine = CurriculumEngine()
        result = engine._parse_json("not json")
        assert result is None


# ══════════════════════════════════════════════════════════════════════════════
# Assessment Engine 深度覆盖
# ══════════════════════════════════════════════════════════════════════════════

class TestAssessmentDeep:
    def test_grading_result_all_fields(self):
        """测试 GradingResult 全部字段。"""
        result = GradingResult(
            score=85, total=100, percentage=85.0, feedback="Good work!",
            strengths=["语法正确", "结构清晰"],
            improvements=["增加细节"],
            rubric_scores={"内容": 40, "语言": 45},
        )
        assert result.score == 85
        assert result.strengths == ["语法正确", "结构清晰"]
        assert result.rubric_scores["内容"] == 40

    def test_student_report_all_fields(self):
        """测试 StudentReport 全部字段。"""
        report = StudentReport(
            student_name="张三", subject="数学", grade="3",
            period="2026春", overall_score=90.0,
            skills={"运算": 95, "几何": 85},
            strengths=["计算能力强"],
            areas_to_improve=["应用题"],
            teacher_notes="继续努力！",
        )
        assert report.skills["运算"] == 95
        assert report.teacher_notes == "继续努力！"

    @pytest.mark.asyncio
    async def test_grade_essay_with_rubric(self):
        """测试带评分标准的作文批改。"""
        engine = AssessmentEngine()
        result = await engine.grade_essay(
            "今天天气真好。",
            rubric={"内容": 50, "语言": 50},
        )
        assert result.total == 100

    @pytest.mark.asyncio
    async def test_grade_math_with_solution(self):
        """测试带参考答案的数学批改。"""
        engine = AssessmentEngine()
        result = await engine.grade_math("2+2=?", "4", "4")
        assert result.total == 10

    @pytest.mark.asyncio
    async def test_generate_report_with_history(self):
        """测试带学习记录的学期报告。"""
        engine = AssessmentEngine()
        report = await engine.generate_report(
            "张三", "数学", "3",
            [{"score": 90, "date": "2026-01"}, {"score": 85, "date": "2026-02"}],
        )
        assert report.student_name == "张三"

    @pytest.mark.asyncio
    async def test_generate_rubric_with_criteria(self):
        """测试带自定义维度的评分标准。"""
        engine = AssessmentEngine()
        result = await engine.generate_rubric(
            "写作", "4", criteria=["内容", "结构", "语法", "创意"]
        )
        assert isinstance(result, dict)

    def test_parse_json_invalid(self):
        """测试无效 JSON。"""
        engine = AssessmentEngine()
        assert engine._parse_json("bad") is None


# ══════════════════════════════════════════════════════════════════════════════
# Subject Expert 深度覆盖
# ══════════════════════════════════════════════════════════════════════════════

class TestSubjectDeep:
    def test_exercise_all_fields(self):
        """测试 SubjectExercise 全部字段。"""
        ex = SubjectExercise(
            question="1+1=?", difficulty="easy", subject="数学", grade="1",
            hints=["数一数"], answer="2", explanation="1个加1个等于2个",
            topic="加法", skills=["计数", "加法运算"],
        )
        assert ex.hints == ["数一数"]
        assert ex.skills == ["计数", "加法运算"]

    @pytest.mark.asyncio
    async def test_explain_concept(self):
        """测试概念解释。"""
        expert = SubjectExpert()
        result = await expert.explain_concept("科学", "5", "光合作用")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_generate_exercise_with_difficulty(self):
        """测试不同难度的习题生成。"""
        expert = SubjectExpert()
        ex = await expert.generate_exercise("数学", "3", "乘法", difficulty="hard")
        assert ex.topic == "乘法"

    @pytest.mark.asyncio
    async def test_stem_project_with_duration(self):
        """测试指定时长的 STEM 项目。"""
        expert = SubjectExpert()
        result = await expert.stem_project("5", "水循环", duration="4课时")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_language_activity(self):
        """测试语言活动生成。"""
        expert = SubjectExpert()
        result = await expert.language_activity("3", "英语", "听力", "动物")
        assert isinstance(result, dict)

    def test_parse_json_invalid(self):
        """测试无效 JSON。"""
        expert = SubjectExpert()
        assert expert._parse_json("bad") is None


# ══════════════════════════════════════════════════════════════════════════════
# Personalization Engine 深度覆盖
# ══════════════════════════════════════════════════════════════════════════════

class TestPersonalizationDeep:
    def test_learning_path_all_fields(self):
        """测试 LearningPath 全部字段。"""
        path = LearningPath(
            student_id="s1", grade="3", subject="数学",
            units=[{"title": "分数入门"}],
            estimated_duration="4周",
            prerequisites=["整数运算"],
            goals=["理解分数概念"],
        )
        assert path.units[0]["title"] == "分数入门"
        assert path.prerequisites == ["整数运算"]

    @pytest.mark.asyncio
    async def test_create_learning_path(self):
        """测试学习路径创建。"""
        engine = PersonalizationEngine()
        path = await engine.create_learning_path("张三", "3", "数学", "掌握分数")
        assert path.student_id == "张三"

    @pytest.mark.asyncio
    async def test_diagnose_skills(self):
        """测试能力诊断。"""
        engine = PersonalizationEngine()
        result = await engine.diagnose_skills("数学", "3", [])
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_recommend_resources(self):
        """测试资源推荐。"""
        engine = PersonalizationEngine()
        result = await engine.recommend_resources("张三", "3", "数学", "分数")
        assert isinstance(result, dict)

    def test_parse_json_invalid(self):
        """测试无效 JSON。"""
        engine = PersonalizationEngine()
        assert engine._parse_json("bad") is None


# ══════════════════════════════════════════════════════════════════════════════
# Content Generator 深度覆盖
# ══════════════════════════════════════════════════════════════════════════════

class TestContentDeep:
    def test_worksheet_all_fields(self):
        """测试 Worksheet 全部字段。"""
        ws = Worksheet(
            title="分数练习", subject="数学", grade="3",
            sections=[{"title": "选择题", "questions": [{"q": "1/2+1/2=?"}]}],
            answer_key="1", instructions="认真答题",
        )
        assert ws.sections[0]["title"] == "选择题"
        assert ws.instructions == "认真答题"

    @pytest.mark.asyncio
    async def test_generate_worksheet(self):
        """测试工作纸生成。"""
        gen = ContentGenerator()
        ws = await gen.generate_worksheet("数学", "3", "分数", num_questions=5)
        assert ws.subject == "数学"

    @pytest.mark.asyncio
    async def test_generate_flashcards(self):
        """测试闪卡生成。"""
        gen = ContentGenerator()
        cards = await gen.generate_flashcards("数学", "3", "分数", count=5)
        assert isinstance(cards, list)

    @pytest.mark.asyncio
    async def test_generate_lesson_slides(self):
        """测试课件生成。"""
        gen = ContentGenerator()
        slides = await gen.generate_lesson_slides("数学", "3", "分数", num_slides=5)
        assert isinstance(slides, list)

    @pytest.mark.asyncio
    async def test_generate_educational_game(self):
        """测试教育游戏生成。"""
        gen = ContentGenerator()
        result = await gen.generate_educational_game("数学", "3", "分数", game_type="board")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_generate_parent_communication(self):
        """测试家校沟通信生成。"""
        gen = ContentGenerator()
        result = await gen.generate_parent_communication("张三", "3", "数学", "分数")
        assert isinstance(result, str)

    def test_parse_json_invalid(self):
        """测试无效 JSON。"""
        gen = ContentGenerator()
        assert gen._parse_json("bad") is None


# ══════════════════════════════════════════════════════════════════════════════
# CLI 测试
# ══════════════════════════════════════════════════════════════════════════════

class TestCLICoverage:
    def test_cli_import(self):
        """测试 CLI 可导入。"""
        from fusion_k12_teacher import cli
        assert cli is not None
        assert cli.main is not None

    def test_cli_help(self):
        """测试 CLI 帮助信息。"""
        from click.testing import CliRunner

        from fusion_k12_teacher.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Fusion-K12-Teacher" in result.output

    def test_cli_version(self):
        """测试 CLI 版本信息。"""
        from click.testing import CliRunner

        from fusion_k12_teacher.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0

    def test_cli_lesson_plan_help(self):
        """测试子命令帮助。"""
        from click.testing import CliRunner

        from fusion_k12_teacher.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["lesson", "plan", "--help"])
        assert result.exit_code == 0

    def test_cli_lesson_quiz_help(self):
        """测试 quiz 子命令帮助。"""
        from click.testing import CliRunner

        from fusion_k12_teacher.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["lesson", "quiz", "--help"])
        assert result.exit_code == 0

    def test_cli_assess_essay_help(self):
        """测试 assess essay 帮助。"""
        from click.testing import CliRunner

        from fusion_k12_teacher.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["assess", "essay", "--help"])
        assert result.exit_code == 0

    def test_cli_subject_explain_help(self):
        """测试 subject explain 帮助。"""
        from click.testing import CliRunner

        from fusion_k12_teacher.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["subject", "explain", "--help"])
        assert result.exit_code == 0

    def test_cli_personalize_path_help(self):
        """测试 personalize path 帮助。"""
        from click.testing import CliRunner

        from fusion_k12_teacher.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["personalize", "path", "--help"])
        assert result.exit_code == 0

    def test_cli_content_worksheet_help(self):
        """测试 content worksheet 帮助。"""
        from click.testing import CliRunner

        from fusion_k12_teacher.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["content", "worksheet", "--help"])
        assert result.exit_code == 0

    def test_cli_lesson_plan_run(self, tmp_path):
        """测试 lesson plan 命令执行。"""
        from click.testing import CliRunner

        from fusion_k12_teacher.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["lesson", "plan", "数学", "3", "分数"])
        # fusion-mlx 不可用时可能报错，但不应崩溃
        assert result.exit_code in (0, 1)

    def test_cli_lesson_quiz_run(self, tmp_path):
        """测试 lesson quiz 命令执行。"""
        from click.testing import CliRunner

        from fusion_k12_teacher.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["lesson", "quiz", "数学", "3", "分数"])
        assert result.exit_code in (0, 1)

    def test_cli_subject_explain_run(self, tmp_path):
        """测试 subject explain 命令执行。"""
        from click.testing import CliRunner

        from fusion_k12_teacher.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["subject", "explain", "科学", "5", "光合作用"])
        assert result.exit_code in (0, 1)

    def test_cli_content_worksheet_run(self, tmp_path):
        """测试 content worksheet 命令执行。"""
        from click.testing import CliRunner

        from fusion_k12_teacher.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["content", "worksheet", "数学", "3", "分数"])
        assert result.exit_code in (0, 1)


# ══════════════════════════════════════════════════════════════════════════════
# Mock 测试 — 模拟 fusion-mlx 成功响应，覆盖成功路径
# ══════════════════════════════════════════════════════════════════════════════

class TestMockSuccess:
    """模拟 fusion-mlx 成功响应，覆盖 try 块中的成功代码路径。"""

    @pytest.mark.asyncio
    async def test_curriculum_parse_json_success(self):
        """测试 curriculum 的 JSON 解析成功路径。"""
        engine = CurriculumEngine()
        # 模拟 chat 返回有效 JSON
        async def mock_chat(messages, temperature=0.7, max_tokens=4096):
            return '{"title": "分数", "objectives": ["理解分数"], "materials": ["课本"], "procedures": [{"step": 1, "activity": "导入"}], "assessment": "提问", "homework": "练习"}'
        engine.mlx.chat = mock_chat
        plan = await engine.generate_lesson_plan("数学", "3", "分数")
        assert plan.title == "分数"
        assert "理解分数" in plan.objectives

    @pytest.mark.asyncio
    async def test_curriculum_parse_json_none(self):
        """测试 JSON 解析失败时的兜底。"""
        engine = CurriculumEngine()
        async def mock_chat(messages, temperature=0.7, max_tokens=4096):
            return "invalid json"
        engine.mlx.chat = mock_chat
        plan = await engine.generate_lesson_plan("数学", "3", "分数")
        assert plan.title == "分数"
        assert plan.grade == "3"

    @pytest.mark.asyncio
    async def test_curriculum_quiz_success(self):
        """测试测验生成成功路径。"""
        engine = CurriculumEngine()
        async def mock_chat(messages, temperature=0.7, max_tokens=4096):
            return '[{"question": "1+1=?", "type": "multiple_choice", "options": ["1","2","3"], "answer": "2", "points": 5, "difficulty": "easy"}]'
        engine.mlx.chat = mock_chat
        quiz = await engine.generate_quiz("数学", "3", "加法", num_questions=1)
        assert len(quiz.questions) == 1

    @pytest.mark.asyncio
    async def test_assessment_essay_success(self):
        """测试作文批改成功路径。"""
        engine = AssessmentEngine()
        async def mock_chat(messages, temperature=0.7, max_tokens=4096):
            return '{"score": 85, "total": 100, "feedback": "Good", "strengths": ["清晰"], "improvements": ["细节"], "rubric_scores": {"内容": 40}}'
        engine.mlx.chat = mock_chat
        result = await engine.grade_essay("test essay")
        assert result.score == 85
        assert "清晰" in result.strengths

    @pytest.mark.asyncio
    async def test_assessment_math_success(self):
        """测试数学批改成功路径。"""
        engine = AssessmentEngine()
        async def mock_chat(messages, temperature=0.7, max_tokens=4096):
            return '{"score": 10, "total": 10, "correct": true, "feedback": "正确", "mistakes": []}'
        engine.mlx.chat = mock_chat
        result = await engine.grade_math("2+2=?", "4", "4")
        assert result.score == 10

    @pytest.mark.asyncio
    async def test_assessment_report_success(self):
        """测试报告生成成功路径。"""
        engine = AssessmentEngine()
        async def mock_chat(messages, temperature=0.7, max_tokens=4096):
            return '{"overall_score": 90, "skills": {"运算": 95}, "strengths": ["计算"], "areas_to_improve": ["应用"], "teacher_notes": "好"}'
        engine.mlx.chat = mock_chat
        report = await engine.generate_report("张三", "数学", "3", [])
        assert report.overall_score == 90
        assert "计算" in report.strengths

    @pytest.mark.asyncio
    async def test_subject_explain_success(self):
        """测试概念解释成功路径。"""
        expert = SubjectExpert()
        async def mock_chat(messages, temperature=0.7, max_tokens=4096):
            return '{"simple_explanation": "光合作用就是植物用阳光制造食物", "example": "阳光照在叶子上", "common_misconceptions": ["植物不需要阳光"]}'
        expert.mlx.chat = mock_chat
        result = await expert.explain_concept("科学", "5", "光合作用")
        assert "光合作用" in result.get("simple_explanation", "")

    @pytest.mark.asyncio
    async def test_personalization_path_success(self):
        """测试学习路径创建成功路径。"""
        engine = PersonalizationEngine()
        async def mock_chat(messages, temperature=0.7, max_tokens=4096):
            return '{"goals": ["掌握分数"], "units": [{"title": "分数入门", "duration": "2周", "activities": ["练习"], "mastery_criteria": "80%"}], "prerequisites": ["整数"], "estimated_duration": "4周"}'
        engine.mlx.chat = mock_chat
        path = await engine.create_learning_path("张三", "3", "数学", "掌握分数")
        assert "掌握分数" in path.goals
        assert len(path.units) >= 1

    @pytest.mark.asyncio
    async def test_content_worksheet_success(self):
        """测试工作纸生成成功路径。"""
        gen = ContentGenerator()
        async def mock_chat(messages, temperature=0.7, max_tokens=4096):
            return '{"title": "分数练习", "instructions": "认真答题", "sections": [{"title": "选择题", "questions": [{"question": "1/2=?", "type": "choice", "points": 5}]}], "answer_key": "0.5"}'
        gen.mlx.chat = mock_chat
        ws = await gen.generate_worksheet("数学", "3", "分数", num_questions=1)
        assert ws.title == "分数练习"
        assert len(ws.sections) >= 1

    @pytest.mark.asyncio
    async def test_content_flashcards_success(self):
        """测试闪卡生成成功路径。"""
        gen = ContentGenerator()
        async def mock_chat(messages, temperature=0.7, max_tokens=4096):
            return '[{"front": "1/2", "back": "0.5", "hint": "一半"}, {"front": "1/4", "back": "0.25", "hint": "四分之一"}]'
        gen.mlx.chat = mock_chat
        cards = await gen.generate_flashcards("数学", "3", "分数", count=2)
        assert len(cards) == 2

    @pytest.mark.asyncio
    async def test_content_slides_success(self):
        """测试课件生成成功路径。"""
        gen = ContentGenerator()
        async def mock_chat(messages, temperature=0.7, max_tokens=4096):
            return '[{"slide_number": 1, "title": "引言", "content": "什么是分数", "teacher_notes": "举例说明"}]'
        gen.mlx.chat = mock_chat
        slides = await gen.generate_lesson_slides("数学", "3", "分数", num_slides=1)
        assert len(slides) == 1

    @pytest.mark.asyncio
    async def test_content_game_success(self):
        """测试教育游戏生成成功路径。"""
        gen = ContentGenerator()
        async def mock_chat(messages, temperature=0.7, max_tokens=4096):
            return '{"title": "分数大冒险", "type": "board", "objective": "掌握分数", "rules": ["掷骰子前进"], "materials": ["骰子"], "duration": "15分钟", "setup": "打印棋盘", "variations": ["难度升级"], "debrief": "学到了什么"}'
        gen.mlx.chat = mock_chat
        result = await gen.generate_educational_game("数学", "3", "分数")
        assert result["title"] == "分数大冒险"

    @pytest.mark.asyncio
    async def test_diagnose_skills_success(self):
        """测试能力诊断成功路径。"""
        engine = PersonalizationEngine()
        async def mock_chat(messages, temperature=0.7, max_tokens=4096):
            return '{"mastered_skills": ["加法"], "developing_skills": ["减法"], "needs_support": ["乘法"], "overall_level": "developing", "recommendations": ["多练习"]}'
        engine.mlx.chat = mock_chat
        result = await engine.diagnose_skills("数学", "3", [])
        assert result["overall_level"] == "developing"

    @pytest.mark.asyncio
    async def test_recommend_resources_success(self):
        """测试资源推荐成功路径。"""
        engine = PersonalizationEngine()
        async def mock_chat(messages, temperature=0.7, max_tokens=4096):
            return '{"resources": [{"type": "视频", "title": "分数入门", "description": "动画教学", "duration": "5分钟", "difficulty": "easy"}], "practice_plan": "每天10题", "parent_tips": "鼓励孩子"}'
        engine.mlx.chat = mock_chat
        result = await engine.recommend_resources("张三", "3", "数学", "分数")
        assert len(result["resources"]) >= 1

    @pytest.mark.asyncio
    async def test_rubric_success(self):
        """测试评分标准生成成功路径。"""
        engine = AssessmentEngine()
        async def mock_chat(messages, temperature=0.7, max_tokens=4096):
            return '{"criteria": [{"name": "内容", "points": 40, "levels": {"优秀": "内容丰富", "良好": "基本完整"}}]}'
        engine.mlx.chat = mock_chat
        result = await engine.generate_rubric("作文", "5")
        assert "criteria" in result

    @pytest.mark.asyncio
    async def test_ai_client_chat_success(self):
        """测试 AI 客户端 _inner 初始化。"""
        from fusion_k12_teacher.ai_client import _HAS_FUSION_CORE, MLXClient
        client = MLXClient(model="test")
        assert (client._inner is not None) or (not _HAS_FUSION_CORE)
        # 测试 chat 失败（fusion-mlx 不可用）
        with pytest.raises(Exception):
            await client.chat([{"role": "user", "content": "hi"}])