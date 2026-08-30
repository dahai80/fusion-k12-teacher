"""v0.3 课标+分层教学 模块测试。"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from fusion_k12_teacher.differentiation import (
    LEVEL_CONFIGS,
    DifferentiatedContent,
    DifferentiationEngine,
    GroupTask,
    LayerContent,
)
from fusion_k12_teacher.standards import (
    AlignmentContext,
    CurriculumStandard,
    KnowledgePoint,
    StandardsAligner,
    StandardsLoader,
    StandardsQuery,
)

# ══════════════════════════════════════════════════════════════════════════════
# Standards Models
# ══════════════════════════════════════════════════════════════════════════════

class TestKnowledgePoint:
    def test_from_dict(self):
        data = {
            "id": "math-g3-na-05",
            "subject": "数学",
            "grade": "3",
            "strand": "数与代数",
            "topic": "分数的初步认识",
            "description": "初步认识分数",
            "prerequisites": ["math-g2-na-04"],
            "progression_next": ["math-g4-na-05"],
            "difficulty_level": "standard",
            "curriculum_code": "2022-数学-3-NA.5",
        }
        kp = KnowledgePoint.from_dict(data)
        assert kp.id == "math-g3-na-05"
        assert kp.subject == "数学"
        assert kp.grade == "3"
        assert kp.prerequisites == ["math-g2-na-04"]
        assert kp.progression_next == ["math-g4-na-05"]

    def test_to_dict(self):
        kp = KnowledgePoint(id="test-01", subject="数学", grade="3", topic="测试")
        d = kp.to_dict()
        assert d["id"] == "test-01"
        assert d["subject"] == "数学"
        assert d["prerequisites"] == []

    def test_default_values(self):
        kp = KnowledgePoint()
        assert kp.id == ""
        assert kp.difficulty_level == "standard"
        assert kp.prerequisites == []


class TestCurriculumStandard:
    def test_from_dict(self):
        data = {
            "id": "math-g1-6",
            "name": "小学数学课标",
            "year": "2022",
            "subject": "数学",
            "grade_range": "1-6",
            "knowledge_points": [
                {"id": "kp1", "subject": "数学", "grade": "1", "topic": "认识数字"}
            ],
        }
        std = CurriculumStandard.from_dict(data)
        assert std.id == "math-g1-6"
        assert len(std.knowledge_points) == 1
        assert std.knowledge_points[0].topic == "认识数字"

    def test_to_dict(self):
        std = CurriculumStandard(id="test", knowledge_points=[KnowledgePoint(id="kp1")])
        d = std.to_dict()
        assert d["id"] == "test"
        assert len(d["knowledge_points"]) == 1


# ══════════════════════════════════════════════════════════════════════════════
# Standards Loader
# ══════════════════════════════════════════════════════════════════════════════

class TestStandardsLoader:
    def test_load_real_data(self):
        loader = StandardsLoader()
        loader.load_all()
        assert len(loader.all_standards()) >= 1
        assert len(loader.all_points()) >= 50

    def test_list_subjects(self):
        loader = StandardsLoader()
        loader.load_all()
        subjects = loader.list_subjects()
        assert "数学" in subjects

    def test_list_grades(self):
        loader = StandardsLoader()
        loader.load_all()
        grades = loader.list_grades("数学")
        assert "3" in grades

    def test_get_point(self):
        loader = StandardsLoader()
        loader.load_all()
        kp = loader.get_point("math-g3-na-05")
        assert kp is not None
        assert kp.topic == "分数的初步认识"

    def test_get_point_not_found(self):
        loader = StandardsLoader()
        loader.load_all()
        kp = loader.get_point("nonexistent")
        assert kp is None

    def test_load_from_custom_dir(self, tmp_path):
        data_file = tmp_path / "test.json"
        data_file.write_text(json.dumps({
            "id": "test-std",
            "name": "测试课标",
            "year": "2024",
            "subject": "测试",
            "grade_range": "1",
            "knowledge_points": [
                {"id": "test-kp-01", "subject": "测试", "grade": "1", "topic": "测试主题"}
            ],
        }), encoding="utf-8")
        loader = StandardsLoader(data_dir=tmp_path)
        loader.load_all()
        assert len(loader.all_points()) == 1
        assert loader.get_point("test-kp-01") is not None

    def test_reload(self):
        loader = StandardsLoader()
        loader.load_all()
        first_count = len(loader.all_points())
        loader.reload()
        second_count = len(loader.all_points())
        assert first_count == second_count

    def test_empty_data_dir(self, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        loader = StandardsLoader(data_dir=empty_dir)
        loader.load_all()
        assert len(loader.all_points()) == 0

    def test_compatible_format(self, tmp_path):
        data_file = tmp_path / "compat.json"
        data_file.write_text(json.dumps({
            "subject": "语文",
            "grade": "1",
            "points": [
                {"id": "cn-g1-01", "topic": "拼音"}
            ],
        }), encoding="utf-8")
        loader = StandardsLoader(data_dir=tmp_path)
        loader.load_all()
        kp = loader.get_point("cn-g1-01")
        assert kp is not None
        assert kp.subject == "语文"


# ══════════════════════════════════════════════════════════════════════════════
# Standards Query
# ══════════════════════════════════════════════════════════════════════════════

class TestStandardsQuery:
    def setup_method(self):
        self.loader = StandardsLoader()
        self.loader.load_all()
        self.query = StandardsQuery(self.loader)

    def test_get_knowledge_points(self):
        points = self.query.get_knowledge_points("数学", "3")
        assert len(points) > 0
        assert all(p.subject == "数学" for p in points)
        assert all(p.grade == "3" for p in points)

    def test_get_knowledge_points_empty(self):
        points = self.query.get_knowledge_points("不存在", "99")
        assert len(points) == 0

    def test_get_prerequisites(self):
        pres = self.query.get_prerequisites("math-g3-na-05")
        assert len(pres) > 0
        assert pres[0].id == "math-g2-na-04"

    def test_get_prerequisites_not_found(self):
        pres = self.query.get_prerequisites("nonexistent")
        assert pres == []

    def test_get_progression(self):
        nxts = self.query.get_progression("math-g3-na-05")
        assert len(nxts) > 0
        assert nxts[0].id == "math-g4-na-05"

    def test_find_by_topic(self):
        points = self.query.find_by_topic("数学", "3", "分数")
        assert len(points) > 0
        assert any("分数" in p.topic for p in points)

    def test_validate_coverage(self):
        report = self.query.validate_coverage("数学", "3", ["分数的初步认识", "万以内数的认识"])
        assert report.total_points > 0
        assert report.covered_points > 0
        assert 0 < report.coverage_ratio <= 1.0

    def test_validate_coverage_empty(self):
        report = self.query.validate_coverage("不存在", "99", [])
        assert report.total_points == 0

    def test_get_strands(self):
        strands = self.query.get_strands("数学", "3")
        assert "数与代数" in strands

    def test_get_by_strand(self):
        points = self.query.get_by_strand("数学", "3", "数与代数")
        assert len(points) > 0
        assert all(p.strand == "数与代数" for p in points)

    def test_get_by_difficulty(self):
        points = self.query.get_by_difficulty("数学", "3", "basic")
        assert len(points) > 0
        assert all(p.difficulty_level == "basic" for p in points)


# ══════════════════════════════════════════════════════════════════════════════
# Standards Aligner
# ══════════════════════════════════════════════════════════════════════════════

class TestStandardsAligner:
    def setup_method(self):
        self.loader = StandardsLoader()
        self.loader.load_all()
        self.query = StandardsQuery(self.loader)
        self.aligner = StandardsAligner(self.query)

    def test_align(self):
        ctx = self.aligner.align("数学", "3", "分数")
        assert len(ctx.knowledge_points) > 0
        assert len(ctx.curriculum_codes) > 0
        assert len(ctx.suggested_objectives) > 0

    def test_build_prompt_context(self):
        ctx = self.aligner.align("数学", "3", "分数")
        text = self.aligner.build_prompt_context(ctx)
        assert "课标对齐要求" in text
        assert "课标编码" in text

    def test_build_prompt_context_empty(self):
        empty_ctx = AlignmentContext()
        text = self.aligner.build_prompt_context(empty_ctx)
        assert text == ""

    def test_validate_alignment(self):
        result = self.aligner.validate_alignment(
            "数学", "3", ["分数的初步认识", "万以内数的认识"]
        )
        assert "aligned" in result
        assert "coverage" in result


# ══════════════════════════════════════════════════════════════════════════════
# Differentiation Models & Config
# ══════════════════════════════════════════════════════════════════════════════

class TestDifferentiationModels:
    def test_layer_content_to_dict(self):
        lc = LayerContent(
            explanation="测试讲解",
            examples=["例1"],
            exercises=[{"q": "1+1", "a": "2"}],
        )
        d = lc.to_dict()
        assert d["explanation"] == "测试讲解"
        assert len(d["examples"]) == 1

    def test_differentiated_content_to_dict(self):
        # E3: layers 改 dict
        dc = DifferentiatedContent(
            topic="分数",
            grade="3",
            subject="数学",
            layers={
                "struggling": LayerContent(explanation="基础讲解"),
                "standard": LayerContent(explanation="标准讲解"),
                "advanced": LayerContent(explanation="拓展讲解"),
            },
        )
        d = dc.to_dict()
        assert d["topic"] == "分数"
        assert d["layers"]["struggling"]["explanation"] == "基础讲解"

    def test_group_task_to_dict(self):
        gt = GroupTask(group_name="A组", task_description="基础任务")
        d = gt.to_dict()
        assert d["group_name"] == "A组"


class TestLevelConfigs:
    def test_three_levels(self):
        assert "struggling" in LEVEL_CONFIGS
        assert "standard" in LEVEL_CONFIGS
        assert "advanced" in LEVEL_CONFIGS

    def test_config_fields(self):
        for level_name, config in LEVEL_CONFIGS.items():
            assert "label" in config
            assert "prompt_modifier" in config
            assert "exercise_count" in config
            assert isinstance(config["exercise_count"], int)

    def test_struggling_has_scaffold(self):
        assert LEVEL_CONFIGS["struggling"]["scaffold_steps"] is True
        assert LEVEL_CONFIGS["struggling"]["extension"] is False

    def test_advanced_has_extension(self):
        assert LEVEL_CONFIGS["advanced"]["extension"] is True
        assert LEVEL_CONFIGS["advanced"]["scaffold_steps"] is False


# ══════════════════════════════════════════════════════════════════════════════
# Differentiation Engine (mock-based)
# ══════════════════════════════════════════════════════════════════════════════

class TestDifferentiationEngineMock:
    def setup_method(self):
        self.loader = StandardsLoader()
        self.loader.load_all()
        self.query = StandardsQuery(self.loader)
        self.engine = DifferentiationEngine(standards_query=self.query)
        self.mock_response = json.dumps({
            "explanation": "测试讲解",
            "examples": ["例1", "例2"],
            "exercises": [{"question": "1+1=?", "answer": "2", "hint": "数一数", "difficulty": "easy"}],
            "hints": ["提示1"],
            "extension": "",
        })

    @pytest.mark.asyncio
    async def test_generate_differentiated_lesson(self):
        self.engine.mlx.chat = AsyncMock(return_value=self.mock_response)
        result = await self.engine.generate_differentiated_lesson("数学", "3", "分数")
        assert isinstance(result, DifferentiatedContent)
        assert result.topic == "分数"
        assert result.subject == "数学"
        assert result.grade == "3"
        # E3: layers 改 dict, 三层应在 layers 内
        assert isinstance(result.layers["struggling"], LayerContent)
        assert isinstance(result.layers["standard"], LayerContent)
        assert isinstance(result.layers["advanced"], LayerContent)

    @pytest.mark.asyncio
    async def test_generate_differentiated_quiz(self):
        quiz_response = json.dumps([
            {"question": "1+1=?", "type": "选择", "answer": "2", "points": 5, "difficulty": "easy"}
        ])
        self.engine.mlx.chat = AsyncMock(return_value=quiz_response)
        result = await self.engine.generate_differentiated_quiz("数学", "3", "分数", num_questions=3)
        assert isinstance(result, DifferentiatedContent)
        assert result.topic == "分数"

    @pytest.mark.asyncio
    async def test_generate_differentiated_lesson_failure(self):
        self.engine.mlx.chat = AsyncMock(side_effect=Exception("LLM error"))
        result = await self.engine.generate_differentiated_lesson("数学", "3", "分数")
        assert isinstance(result, DifferentiatedContent)
        # E3: 失败层降级空 LayerContent, 走 layers dict
        assert result.layers["struggling"].explanation == ""
        assert result.layers["standard"].explanation == ""
        assert result.layers["advanced"].explanation == ""

    @pytest.mark.asyncio
    async def test_parse_json_with_code_block(self):
        self.engine.mlx.chat = AsyncMock(return_value='```json\n{"explanation": "test"}\n```')
        result = await self.engine._generate_layer(
            "数学", "3", "分数", "standard", 45, ""
        )
        assert result.explanation == "test"

    @pytest.mark.asyncio
    async def test_group_tasks_generation(self):
        group_response = json.dumps([
            {"group_name": "A组(基础)", "task_description": "基础任务", "expected_output": "基础成果", "time_allocation": "15分钟"},
        ])
        self.engine.mlx.chat = AsyncMock(return_value=group_response)
        tasks = await self.engine._generate_group_tasks("数学", "3", "分数", 45)
        assert len(tasks) == 1
        assert tasks[0].group_name == "A组(基础)"

    @pytest.mark.asyncio
    async def test_standards_context_injected(self):
        call_args = []

        async def capture_chat(messages, **kwargs):
            call_args.append(messages)
            return self.mock_response

        self.engine.mlx.chat = capture_chat
        await self.engine.generate_differentiated_lesson("数学", "3", "分数")
        assert len(call_args) >= 3
        user_msg = call_args[0][1]["content"]
        assert "课标对齐要求" in user_msg
