"""课程平台抽象层测试 — 平台-内容解耦、学科注册、通用 DSL。"""

from __future__ import annotations

import pytest

from fusion_k12_teacher.course import (
    FALLBACK_TYPES,
    VISUAL_TYPES,
    Checkpoint,
    CheckpointType,
    FallbackType,
    FusionSocraticDSL,
    MasteryTracker,
    OnErrorAction,
    SceneDSL,
    SubjectNotFoundError,
    SubjectRegistry,
    TeachingStep,
    VisualState,
    VisualType,
)
from fusion_k12_teacher.course.subjects.math import MathSubject


def test_subject_module_manifest():
    m = MathSubject()
    manifest = m.to_manifest()
    assert manifest["subject_id"] == "math"
    assert manifest["display_name"] == "数学"
    assert manifest["capabilities"]["knowledge_graph"] is True
    assert manifest["capabilities"]["verifier"] is True


def test_subject_registry_get_not_found():
    r = SubjectRegistry()
    with pytest.raises(SubjectNotFoundError):
        r.get("physics")


def test_subject_registry_register_and_list():
    r = SubjectRegistry()
    r.register(MathSubject())
    assert len(r.list_subjects()) == 1
    assert r.get("math").subject_id == "math"


def test_checkpoint_from_dict_round_trip():
    cp = Checkpoint.from_dict({
        "id": "cp1", "type": "multiple_choice", "prompt": "测试",
        "options": [{"id": "a", "label": "A", "is_correct": True, "feedback": "对"}],
        "on_error_action": "rewind", "difficulty_layer": "B",
    })
    assert cp.type == CheckpointType.MULTIPLE_CHOICE
    assert cp.on_error_action == OnErrorAction.REWIND
    d = cp.to_dict()
    assert d["type"] == "multiple_choice"


def test_checkpoint_invalid_type_defaults():
    cp = Checkpoint.from_dict({"id": "cp1", "type": "bogus", "prompt": ""})
    assert cp.type == CheckpointType.MULTIPLE_CHOICE


def test_scene_dsl_to_dict():
    dsl = SceneDSL(subject="math", template_type="train_crossing_bridge", verified=True)
    d = dsl.to_dict()
    assert d["subject"] == "math"
    assert d["verified"] is True


def test_scene_dsl_version_v3():
    dsl = SceneDSL()
    assert dsl.version == "3.0.0"


def test_fusion_socratic_dsl_scene_is_typed_sceneDSL():
    """issue #19 AC: scene 字段为 SceneDSL 类型 (统一 v3.0 合约)。"""
    dsl = FusionSocraticDSL(subject="math")
    assert isinstance(dsl.scene, SceneDSL)
    d = dsl.to_dict()
    assert isinstance(d["scene"], dict)
    assert d["scene"]["version"] == "3.0.0"


def test_fusion_socratic_dsl_scene_populated():
    dsl = FusionSocraticDSL(
        subject="math",
        scene=SceneDSL(subject="math", template_type="track_timeline",
                       entities=[{"id": "train"}], verified=True),
    )
    d = dsl.to_dict()
    assert d["scene"]["template_type"] == "track_timeline"
    assert d["scene"]["entities"] == [{"id": "train"}]
    assert d["scene"]["verified"] is True


def test_mastery_tracker_cold_start_threshold():
    t = MasteryTracker()
    for _ in range(4):
        t.record("s1", "node_a", True)
    rec = t.get("s1", "node_a")
    assert rec.total == 4
    assert rec.display_ready is False  # N<5 不显热力
    t.record("s1", "node_a", True)
    rec = t.get("s1", "node_a")
    assert rec.total == 5
    assert rec.display_ready is True
    assert rec.heat_color == "green"


def test_mastery_tracker_weak_nodes():
    t = MasteryTracker()
    for _ in range(6):
        t.record("s2", "node_weak", False)
    assert "node_weak" in t.weak_nodes("s2")


# ── issue #19: DSL v3.0 测试 ──────────────────────────────────────────

def test_visual_type_enum_8_primitives():
    assert len(VISUAL_TYPES) == 8
    assert VisualType.ARRAY_GRID.value == "array_grid"
    assert VisualType.TAPE_DIAGRAM.value == "tape_diagram"
    assert VisualType.GEOMETRY_2D.value == "geometry_2d"
    assert VisualType.ISOMETRIC_3D.value == "isometric_3d"
    assert VisualType.TRACK_TIMELINE.value == "track_timeline"
    assert VisualType.BUCKET_DIVIDER.value == "bucket_divider"
    assert VisualType.DATA_CHART.value == "data_chart"
    assert VisualType.FLOW_CARD.value == "flow_card"


def test_fallback_type_enum_2_values():
    assert len(FALLBACK_TYPES) == 2
    assert FallbackType.TAPE_DIAGRAM.value == "tape_diagram"
    assert FallbackType.FLOW_CARD.value == "flow_card"


def test_fusion_socratic_dsl_version_v3():
    dsl = FusionSocraticDSL(subject="math")
    assert dsl.version == "3.0.0"
    d = dsl.to_dict()
    assert d["version"] == "3.0.0"
    assert "scene" in d
    assert "steps" in d


def test_fusion_socratic_dsl_meta_visual_type():
    dsl = FusionSocraticDSL(
        subject="math",
        meta={"title": "过桥问题", "visual_type": "track_timeline",
              "fallback_type": "tape_diagram"},
    )
    assert dsl.meta["visual_type"] == "track_timeline"
    assert dsl.meta["fallback_type"] == "tape_diagram"


def test_visual_state_from_dict_valid():
    vs = VisualState.from_dict({
        "visual_type": "array_grid",
        "action": "进入:展示3行4列阵列",
        "progress_range": [0.0, 0.5],
        "active_entities": ["cell_1", "cell_2"],
        "latex_state": "3 \\times 4 = 12",
    })
    assert vs.visual_type == "array_grid"
    assert vs.action == "进入:展示3行4列阵列"
    assert vs.progress_range == (0.0, 0.5)
    assert vs.active_entities == ["cell_1", "cell_2"]


def test_visual_state_from_dict_invalid_type_fallback():
    vs = VisualState.from_dict({"visual_type": "bogus_viz"})
    assert vs.visual_type == "flow_card"


def test_visual_state_from_dict_bad_progress_range():
    vs = VisualState.from_dict({"progress_range": "not_a_list"})
    assert vs.progress_range == (0.0, 1.0)


def test_teaching_step_has_visual_state():
    step = TeachingStep(step_id="s1", step_title="引入", speech_narration="...")
    assert step.visual_state is not None
    assert step.visual_state.visual_type == ""
    d = step.to_dict()
    assert "visual_state" in d


def test_teaching_step_with_visual_state_round_trip():
    step = TeachingStep(
        step_id="s1", step_title="探索", speech_narration="看图数一数",
        visual_state=VisualState(visual_type="array_grid", action="圈画",
                                 progress_range=(0.1, 0.4),
                                 active_entities=["row1"]),
    )
    d = step.to_dict()
    assert d["visual_state"]["visual_type"] == "array_grid"
    assert d["visual_state"]["action"] == "圈画"


# ── issue #22 gap: BNUP prompt registry referenced at all 8 call sites ──

def test_bnup_system_prompt_imported_at_8_sites():
    """issue #22: BNUP_SYSTEM_PROMPT 应被 8 个 prompt 站点 import, 非仅定义。"""
    import importlib

    sites = [
        "fusion_k12_teacher.course.subjects.math.socratic_tutor",
        "fusion_k12_teacher.course.subjects.math.generic_pipeline",
        "fusion_k12_teacher.course.subjects.math.scene_compiler",
        "fusion_k12_teacher.course.cot_pipeline",
        "fusion_k12_teacher.curriculum.engine",
        "fusion_k12_teacher.assessment.grader",
        "fusion_k12_teacher.subjects.expert",
        "fusion_k12_teacher.digital_human.memory",
    ]
    for site in sites:
        mod = importlib.import_module(site)
        assert hasattr(mod, "BNUP_SYSTEM_PROMPT"), \
            f"{site} does not import BNUP_SYSTEM_PROMPT (issue #22 gap)"


def test_bnup_visual_routing_prompt_imported_at_math_sites():
    """issue #22: BNUP_VISUAL_ROUTING_PROMPT 应被数学 prompt 站点 import。"""
    import importlib

    sites = [
        "fusion_k12_teacher.course.subjects.math.socratic_tutor",
        "fusion_k12_teacher.course.subjects.math.generic_pipeline",
        "fusion_k12_teacher.course.subjects.math.scene_compiler",
        "fusion_k12_teacher.curriculum.engine",
        "fusion_k12_teacher.subjects.expert",
    ]
    for site in sites:
        mod = importlib.import_module(site)
        assert hasattr(mod, "BNUP_VISUAL_ROUTING_PROMPT"), \
            f"{site} does not import BNUP_VISUAL_ROUTING_PROMPT (issue #22 gap)"


def test_bnup_cot_format_prompt_imported_at_cot_pipeline():
    """issue #22: BNUP_COT_FORMAT_PROMPT 应被 cot_pipeline import。"""
    from fusion_k12_teacher.course.cot_pipeline import BNUP_COT_FORMAT_PROMPT
    assert "两阶段" in BNUP_COT_FORMAT_PROMPT or "CoT" in BNUP_COT_FORMAT_PROMPT


def test_inline_prompts_prefixed_with_bnup():
    """issue #22: inline prompt 常量应以 BNUP_SYSTEM_PROMPT 前缀拼接。"""
    from fusion_k12_teacher.course.prompts.bnup_socratic import BNUP_SYSTEM_PROMPT
    from fusion_k12_teacher.course.subjects.math.generic_pipeline import _GENERIC_PROMPT
    from fusion_k12_teacher.course.subjects.math.scene_compiler import _EXTRACT_PROMPT
    from fusion_k12_teacher.course.subjects.math.socratic_tutor import _SCRIPT_PROMPT

    assert _SCRIPT_PROMPT.startswith(BNUP_SYSTEM_PROMPT)
    assert _GENERIC_PROMPT.startswith(BNUP_SYSTEM_PROMPT)
    assert _EXTRACT_PROMPT.startswith(BNUP_SYSTEM_PROMPT)
