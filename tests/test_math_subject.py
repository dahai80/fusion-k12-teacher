"""数学学科测试 — SymPy 校验、知识图谱、场景编译(mock LLM)、苏格拉底课稿(mock LLM)。"""

from __future__ import annotations

import pytest

from fusion_k12_teacher.course.models import Checkpoint, CheckpointType
from fusion_k12_teacher.course.subjects.math.sympy_verifier import MathSympyVerifier


class TestSympyVerifier:
    def setup_method(self):
        self.v = MathSympyVerifier()

    def test_train_crossing_bridge_full_pass(self):
        r = self.v.verify_scene("train_crossing_bridge", {"L_bridge": 800, "L_train": 200, "v_train": 20})
        assert r.verified is True
        assert r.variables["S_total"]["value"] == 1000.0
        assert r.variables["t"]["value"] == 50.0

    def test_train_on_bridge_hidden_condition(self):
        r = self.v.verify_scene("train_on_bridge", {"L_bridge": 800, "L_train": 200, "v_train": 20})
        assert r.variables["S_total"]["value"] == 600.0
        assert r.variables["t"]["value"] == 30.0

    def test_relative_motion(self):
        r = self.v.verify_scene("relative_motion", {"L_train": 180, "v_train": 16, "v_pedestrian": 2})
        assert r.variables["v_relative"]["value"] == 18.0
        assert r.variables["t"]["value"] == 10.0

    def test_two_trains_meet(self):
        r = self.v.verify_scene("two_trains_meet", {"L1": 150, "L2": 250, "v1": 25, "v2": 15})
        assert r.variables["S_total"]["value"] == 400.0
        assert r.variables["v_relative"]["value"] == 40.0
        assert r.variables["t"]["value"] == 10.0

    def test_two_trains_overtake(self):
        r = self.v.verify_scene("two_trains_overtake", {"L1": 150, "L2": 250, "v1": 25, "v2": 15})
        assert r.variables["v_relative"]["value"] == 10.0
        assert r.variables["t"]["value"] == 40.0

    def test_echo_problem(self):
        r = self.v.verify_scene("echo_problem", {"v_train": 20, "v_sound": 340, "t_echo": 2})
        assert r.variables["x_distance"]["value"] == 360.0

    def test_cutting_segments(self):
        r = self.v.verify_scene("cutting_segments", {"n_segments": 3, "time_per_cut": 2})
        assert r.verified is True
        assert r.variables["n_cuts"]["value"] == 2.0
        assert r.variables["total_time"]["value"] == 4.0

    def test_cutting_one_segment_no_cut(self):
        r = self.v.verify_scene("cutting_segments", {"n_segments": 1, "time_per_cut": 5})
        assert r.variables["n_cuts"]["value"] == 0.0
        assert r.variables["total_time"]["value"] == 0.0

    def test_queue_counting(self):
        r = self.v.verify_scene("queue_counting", {"rank_front": 5, "rank_behind": 4})
        assert r.verified is True
        assert r.variables["total_people"]["value"] == 8.0

    def test_fence_against_wall(self):
        r = self.v.verify_scene("fence_against_wall", {"length": 10, "perimeter": 24})
        assert r.variables["width"]["value"] == 7.0
        assert r.variables["area"]["value"] == 70.0

    def test_unitary_method(self):
        r = self.v.verify_scene("unitary_method", {"n_items": 3, "total_value": 6, "n_target": 5})
        assert r.variables["unit_value"]["value"] == 2.0
        assert r.variables["target_value"]["value"] == 10.0

    def test_chicken_rabbit(self):
        r = self.v.verify_scene("chicken_rabbit", {"heads": 10, "legs": 28})
        assert r.variables["rabbit"]["value"] == 4.0
        assert r.variables["chicken"]["value"] == 6.0

    def test_basic_motion(self):
        r = self.v.verify_scene("basic_motion", {"distance": 0, "speed": 20, "time": 5})
        assert r.variables["distance"]["value"] == 100.0

    def test_work_problem(self):
        r = self.v.verify_scene("work_problem", {"worker1_days": 6, "worker2_days": 12})
        assert abs(r.variables["total_days"]["value"] - 4.0) < 0.01

    def test_average_problem(self):
        r = self.v.verify_scene("average_problem", {"total_sum": 360, "count": 4})
        assert r.variables["average"]["value"] == 90.0

    def test_overlap_splice(self):
        r = self.v.verify_scene("overlap_splice", {"board1": 5, "board2": 5, "overlap": 1})
        assert r.variables["total_length"]["value"] == 9.0

    def test_round_trip(self):
        r = self.v.verify_scene("round_trip", {"distance": 450, "trips": 2})
        assert r.variables["total_distance"]["value"] == 1800.0

    def test_sum_multiple(self):
        r = self.v.verify_scene("sum_multiple", {"sum": 40, "multiple": 4})
        assert r.variables["small"]["value"] == 8.0
        assert r.variables["big"]["value"] == 32.0

    def test_sprinkler_area(self):
        r = self.v.verify_scene("sprinkler_area", {"speed": 100, "width": 3, "time": 5})
        assert r.variables["area"]["value"] == 1500.0

    def test_tree_planting_both_ends(self):
        r = self.v.verify_scene("tree_planting", {"length": 20, "spacing": 5, "mode_code": 1})
        assert r.variables["trees"]["value"] == 5.0

    def test_tree_planting_closed(self):
        r = self.v.verify_scene("tree_planting", {"length": 60, "spacing": 10, "mode_code": 0})
        assert r.variables["trees"]["value"] == 6.0

    def test_displacement_volume(self):
        r = self.v.verify_scene("displacement_volume", {"length": 20, "width": 15, "rise": 2})
        assert r.variables["volume"]["value"] == 600.0

    def test_profit_loss(self):
        r = self.v.verify_scene("profit_loss", {"surplus": 10, "deficit": 4, "diff": 2})
        assert r.variables["people"]["value"] == 7.0

    def test_simple_interest(self):
        r = self.v.verify_scene("simple_interest", {"principal": 1000, "rate": 0.02, "years": 2})
        assert r.variables["interest"]["value"] == 40.0
        assert r.variables["total"]["value"] == 1040.0

    def test_tiered_pricing(self):
        r = self.v.verify_scene("tiered_pricing", {"base_distance": 3, "base_price": 8, "unit_price": 2, "total_distance": 5})
        assert r.variables["total_price"]["value"] == 12.0

    def test_weekday_calc(self):
        r = self.v.verify_scene("weekday_calc", {"start_day": 3, "add_days": 25})
        assert r.variables["target_day"]["value"] == 7.0

    def test_semicircle_perimeter(self):
        r = self.v.verify_scene("semicircle_perimeter", {"radius": 3})
        assert abs(r.variables["perimeter"]["value"] - 15.42) < 0.01

    def test_cuboid_combine_surface(self):
        r = self.v.verify_scene("cuboid_combine_surface", {"length": 6, "width": 4, "height": 2})
        assert r.variables["max_sa"]["value"] == 160.0

    def test_combination_count(self):
        r = self.v.verify_scene("combination_count", {"n_items1": 2, "n_items2": 3})
        assert r.variables["combinations"]["value"] == 6.0

    def test_unitary_combined(self):
        r = self.v.verify_scene("unitary_combined", {"n_people": 4, "n_days": 6, "total_work": 240, "target_people": 8, "target_days": 3})
        assert r.variables["result"]["value"] == 240.0

    def test_redundant_filter(self):
        r = self.v.verify_scene("redundant_filter", {"total": 10, "removed": 3, "distraction": 2})
        assert r.verified is True
        assert r.variables["remaining"]["value"] == 7.0

    def test_fold_cut(self):
        r = self.v.verify_scene("fold_cut", {"folds": 2})
        assert r.verified is True
        assert r.variables["segments"]["value"] == 5.0

    def test_stars_bars(self):
        r = self.v.verify_scene("stars_bars", {"n_items": 7, "n_bins": 3})
        assert r.verified is True
        assert r.variables["ways"]["value"] == 15.0

    def test_stars_bars_min_per(self):
        r = self.v.verify_scene("stars_bars", {"n_items": 12, "n_bins": 3, "min_per": 3})
        assert r.verified is True
        assert r.variables["ways"]["value"] == 10.0
        assert r.variables["remaining"]["value"] == 3.0

    def test_stars_bars_default_min_per(self):
        r = self.v.verify_scene("stars_bars", {"n_items": 7, "n_bins": 3, "min_per": 1})
        assert r.variables["ways"]["value"] == 15.0

    def test_unknown_scenario_fallback(self):
        r = self.v.verify_scene("unknown_scene", {})
        assert r.fallback is True
        assert "未知场景" in r.error

    def test_missing_variable(self):
        r = self.v.verify_scene("train_crossing_bridge", {"L_bridge": 800})
        assert r.fallback is True
        assert "缺失变量" in r.error

    def test_judge_expression_equivalent(self):
        cp = Checkpoint(id="cp1", type=CheckpointType.EXPRESSION, prompt="", expected_expression="(800-200)/20")
        result = self.v.judge_checkpoint(cp, "600/20")
        assert result.correct is True
        assert result.method in ("verifier", "numeric_sample")

    def test_judge_expression_not_equivalent(self):
        cp = Checkpoint(id="cp1", type=CheckpointType.EXPRESSION, prompt="", expected_expression="(800-200)/20")
        result = self.v.judge_checkpoint(cp, "(800+200)/20")
        assert result.correct is False

    def test_judge_numeric_correct(self):
        cp = Checkpoint(id="cp1", type=CheckpointType.NUMERIC_INPUT, prompt="", expected_value=50.0, tolerance=0.01)
        assert self.v.judge_checkpoint(cp, "50").correct is True

    def test_judge_numeric_wrong(self):
        cp = Checkpoint(id="cp1", type=CheckpointType.NUMERIC_INPUT, prompt="", expected_value=50.0, tolerance=0.01)
        assert self.v.judge_checkpoint(cp, "30").correct is False

    def test_judge_multiple_choice(self):
        cp = Checkpoint(id="cp1", type=CheckpointType.MULTIPLE_CHOICE, prompt="",
                        options=[{"id": "a", "is_correct": False, "feedback": ""}, {"id": "b", "is_correct": True, "feedback": "对"}])
        assert self.v.judge_checkpoint(cp, "b").correct is True
        assert self.v.judge_checkpoint(cp, "a").correct is False


class TestMathProblemBank:
    def setup_method(self):
        from fusion_k12_teacher.course.subjects.math.problem_bank import MathProblemBank
        self.bank = MathProblemBank()
        self.bank.load()

    def test_loaded_count(self):
        assert self.bank.count == 134

    def test_examples_and_exercises(self):
        examples = self.bank.query(kind="example")
        exercises = self.bank.query(kind="exercise")
        assert len(examples) == 131
        assert len(exercises) == 3

    def test_filter_by_template(self):
        meets = self.bank.query(template_id="two_trains_meet")
        assert all(p.template_id == "two_trains_meet" for p in meets)
        assert len(meets) >= 2

    def test_filter_by_difficulty(self):
        a_layer = self.bank.query(difficulty_layer="A")
        assert all(p.difficulty_layer == "A" for p in a_layer)

    def test_filter_by_misconception(self):
        forget = self.bank.query(misconception_tag="forget_train_length")
        assert all("forget_train_length" in p.misconception_tags for p in forget)
        assert len(forget) >= 2

    def test_filter_by_concept_template(self):
        concepts = self.bank.query(template_id="concept_discrimination")
        assert len(concepts) == 97

    def test_new_scene_templates_present(self):
        for tid in ("queue_counting", "fence_against_wall", "unitary_method",
                    "chicken_rabbit", "basic_motion", "work_problem",
                    "average_problem", "cutting_segments",
                    "overlap_splice", "round_trip", "sum_multiple",
                    "sprinkler_area", "tree_planting",
                    "displacement_volume", "profit_loss",
                    "simple_interest", "tiered_pricing", "weekday_calc",
                    "semicircle_perimeter", "cuboid_combine_surface",
                    "combination_count", "unitary_combined",
                    "redundant_filter", "fold_cut", "stars_bars"):
            assert len(self.bank.query(template_id=tid)) >= 1, f"{tid} 缺题"

    def test_get_by_id(self):
        p = self.bank.get("tb-ex-01")
        assert p is not None
        assert p.template_id == "train_crossing_bridge"
        assert p.expected["t"] == 50.0

    def test_get_404(self):
        assert self.bank.get("nonexistent") is None

    def test_misconceptions_loaded(self):
        miscs = self.bank.misconceptions()
        assert len(miscs) == 125
        ids = [m["id"] for m in miscs]
        assert "forget_train_length" in ids

    def test_formula_cheatsheet(self):
        cheat = self.bank.formula_cheatsheet()
        assert len(cheat) == 20

    def test_triple_tagging(self):
        for p in self.bank.all():
            assert p.knowledge_node_id, f"{p.id} 缺知识点节点"
            assert p.cognitive_level, f"{p.id} 缺认知层级"
            assert isinstance(p.misconception_tags, list)


class TestMathKnowledgeGraph:
    def setup_method(self):
        from fusion_k12_teacher.course.subjects.math.knowledge_graph import MathKnowledgeGraph
        from fusion_k12_teacher.standards import StandardsLoader, StandardsQuery
        loader = StandardsLoader()
        loader.load_all()
        self.q = StandardsQuery(loader)
        self.kg = MathKnowledgeGraph()
        self.kg.load(standards_query=self.q)

    def test_loaded_nodes(self):
        assert self.kg.node_count() == 52
        assert self.kg.edge_count() > 0

    def test_is_dag(self):
        assert self.kg.is_dag() is True

    def test_query_by_grade(self):
        nodes = self.kg.query(grade="5")
        assert len(nodes) > 0
        assert all(n.grade == "5" for n in nodes)

    def test_reverse_attribution(self):
        nodes = self.kg.query(grade="5")
        if nodes:
            chain = self.kg.reverse_attribution(nodes[0].id, max_depth=2)
            assert isinstance(chain, list)

    def test_get_node(self):
        nodes = self.kg.query(grade="1")
        if nodes:
            n = self.kg.get_node(nodes[0].id)
            assert n is not None
            assert n.id == nodes[0].id


class TestSceneCompilerMock:
    @pytest.fixture
    def compiler(self, monkeypatch):
        from fusion_k12_teacher.course.subjects.math.scene_compiler import MathSceneCompiler
        from fusion_k12_teacher.course.subjects.math.sympy_verifier import MathSympyVerifier

        class MockMLX:
            async def chat(self, messages, temperature=0.3, max_tokens=1024):
                return '''{"scenario": "train_crossing_bridge", "entities": {"bridge": {"length": 800, "label": "大桥"}, "train": {"length": 200, "speed": 20, "label": "火车"}}, "key_milestones": [{"time_ratio": 0.0, "label": "车头上桥", "event": "start"}], "question_focus": "calculate_total_time", "misconception_hint": "忘记加车长"}'''

        return MathSceneCompiler(MockMLX(), MathSympyVerifier())

    @pytest.mark.asyncio
    async def test_compile_full_pipeline(self, compiler):
        dsl = await compiler.compile("一列长200米的火车以20米每秒的速度通过800米大桥求通过时间")
        assert dsl.subject == "math"
        assert dsl.template_type == "train_crossing_bridge"
        assert dsl.verified is True
        assert dsl.timeline["total_distance"] == 1000.0
        assert dsl.timeline["total_time"] == 50.0


class TestSocraticTutorMock:
    @pytest.fixture
    def tutor(self, monkeypatch):
        from fusion_k12_teacher.course.subjects.math.socratic_tutor import MathSocraticTutor
        from fusion_k12_teacher.course.subjects.math.sympy_verifier import MathSympyVerifier

        class MockMLX:
            async def chat(self, messages, temperature=0.3, max_tokens=4096):
                return '''{"global_variables": {"L_train": {"label": "车长", "unit": "m", "value": 200, "is_unknown": false}}, "steps": [{"step_id": "step1", "step_title": "观察", "phase": "Engage", "speech_narration": "我们来看火车过桥", "landmarks": [{"timeOffsetMs": 0, "progressRatio": 0.0, "latexHighlightVar": "L_train"}], "animation": {"start_ratio": 0.0, "end_ratio": 0.3, "camera_focus_entity": "train_head", "highlight_entities": ["train_head"]}, "checkpoint": {"id": "cp1", "type": "multiple_choice", "prompt": "路程关系?", "options": [{"id": "a", "label": "桥长+车长", "is_correct": true, "feedback": "对"}], "hints": ["提示"], "on_error_action": "rewind", "difficulty_layer": "B"}}]}'''

        return MathSocraticTutor(MockMLX(), MathSympyVerifier())

    @pytest.mark.asyncio
    async def test_generate_lesson_script(self, tutor):
        dsl = await tutor.generate_lesson_script("火车过桥", grade="5")
        assert dsl.subject == "math"
        assert len(dsl.steps) == 1
        assert dsl.steps[0].checkpoint is not None
        assert dsl.steps[0].phase == "Engage"
