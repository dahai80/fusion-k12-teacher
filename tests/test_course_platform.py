# Course platform abstraction layer tests — platform-content decoupling,
# subject registration, generic DSL.

# i18n: user-facing — Chinese literals below are test fixture data (sample
# titles/topics/labels used as data) and assertion targets on product content
# (prompts, DSL fields); do not translate.

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


# issue #19 AC: the scene field is of type SceneDSL (unified v3.0 contract).
def test_fusion_socratic_dsl_scene_is_typed_sceneDSL():
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
    assert rec.display_ready is False  # N<5: no heatmap display
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


# ── issue #19: DSL v3.0 tests ─────────────────────────────────────────

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

# issue #22: BNUP_SYSTEM_PROMPT must be imported at all 8 prompt sites, not just defined.
def test_bnup_system_prompt_imported_at_8_sites():
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


# issue #22: BNUP_VISUAL_ROUTING_PROMPT must be imported by the math prompt sites.
def test_bnup_visual_routing_prompt_imported_at_math_sites():
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


# issue #22: BNUP_COT_FORMAT_PROMPT must be imported by cot_pipeline.
def test_bnup_cot_format_prompt_imported_at_cot_pipeline():
    from fusion_k12_teacher.course.cot_pipeline import BNUP_COT_FORMAT_PROMPT
    assert "两阶段" in BNUP_COT_FORMAT_PROMPT or "CoT" in BNUP_COT_FORMAT_PROMPT


# issue #22: inline prompt constants must be concatenated with the BNUP_SYSTEM_PROMPT prefix.
def test_inline_prompts_prefixed_with_bnup():
    from fusion_k12_teacher.course.prompts.bnup_socratic import BNUP_SYSTEM_PROMPT
    from fusion_k12_teacher.course.subjects.math.generic_pipeline import _GENERIC_PROMPT
    from fusion_k12_teacher.course.subjects.math.scene_compiler import _EXTRACT_PROMPT
    from fusion_k12_teacher.course.subjects.math.socratic_tutor import _SCRIPT_PROMPT

    assert _SCRIPT_PROMPT.startswith(BNUP_SYSTEM_PROMPT)
    assert _GENERIC_PROMPT.startswith(BNUP_SYSTEM_PROMPT)
    assert _EXTRACT_PROMPT.startswith(BNUP_SYSTEM_PROMPT)


# ── issue #19 P0: spec DSL v3.0 schema compliance (to_spec_dict) ──────

# Build a FusionSocraticDSL with global variables/steps/scene for to_spec_dict tests.
def _build_full_dsl() -> FusionSocraticDSL:
    cp = Checkpoint(
        id="cp1", type=CheckpointType.EXPRESSION,
        prompt="车长+桥长=总路程?", expected_expression="(800+200)/20",
    )
    vs = VisualState(
        visual_type="track_timeline", action="train_run",
        progress_range=(0.0, 0.5), active_entities=["train", "bridge"],
    )
    step = TeachingStep(
        step_id="s1", step_title="观察火车过桥", speech_narration="...",
        phase="Engage", checkpoint=cp, visual_state=vs,
    )
    scene = SceneDSL(
        subject="math", template_type="train_crossing_bridge",
        entities=[
            {"id": "train", "type": "moving_object", "label": "火车", "length": 200},
            {"id": "bridge", "type": "static_structure", "label": "大桥", "length": 800},
        ],
        verified=True,
    )
    return FusionSocraticDSL(
        subject="math",
        meta={"title": "火车过桥", "grade": "5", "visual_type": "track_timeline",
              "fallback_type": "tape_diagram", "knowledge_node_id": "node-5-01"},
        global_variables={
            "L_train": {"label": "车长", "unit": "m", "value": 200},
            "L_bridge": {"label": "桥长", "unit": "m", "value": 800},
            "v_train": {"label": "速度", "unit": "m/s", "value": 20},
            "t": {"label": "时间", "unit": "s", "value": 50},
        },
        steps=[step],
        scene=scene,
    )


# issue #19 P0: to_spec_dict outputs the four spec DSL v3.0 root keys.
def test_to_spec_dict_root_keys():
    dsl = _build_full_dsl()
    spec = dsl.to_spec_dict()
    assert set(spec.keys()) == {"meta", "parameters", "entities", "pipeline"}


# issue #19 P0: meta contains id/grade/topic/visual_type/fallback_type.
def test_to_spec_dict_meta_fields():
    dsl = _build_full_dsl()
    meta = dsl.to_spec_dict()["meta"]
    assert meta["id"] == "node-5-01"
    assert meta["grade"] == 5.0
    assert meta["topic"] == "火车过桥"
    assert meta["visual_type"] == "track_timeline"
    assert meta["fallback_type"] == "tape_diagram"


# issue #19 P0: global_variables → parameters, value coerced to float.
def test_to_spec_dict_parameters_from_global_variables():
    dsl = _build_full_dsl()
    params = dsl.to_spec_dict()["parameters"]
    assert "L_train" in params
    assert params["L_train"]["label"] == "车长"
    assert params["L_train"]["value"] == 200.0
    assert isinstance(params["L_train"]["value"], float)
    assert params["L_train"]["unit"] == "m"
    assert params["t"]["value"] == 50.0


# issue #19 P0: scene.entities → root-level entities array.
def test_to_spec_dict_entities_from_scene():
    dsl = _build_full_dsl()
    entities = dsl.to_spec_dict()["entities"]
    assert len(entities) == 2
    ent = entities[0]
    assert ent["id"] == "train"
    assert ent["type"] == "moving_object"
    assert ent["label"] == "火车"
    assert ent["properties"]["length"] == 200


# issue #19 P0: steps → pipeline, includes step/title/formula/eval/result_unit/visual_state.
def test_to_spec_dict_pipeline_from_steps():
    dsl = _build_full_dsl()
    pipeline = dsl.to_spec_dict()["pipeline"]
    assert len(pipeline) == 1
    p = pipeline[0]
    assert p["step"] == 1
    assert p["title"] == "观察火车过桥"
    assert p["formula"] == "(800+200)/20"
    assert p["eval"] == "(800+200)/20"
    assert "visual_state" in p
    assert p["visual_state"]["progress_range"] == [0.0, 0.5]
    assert p["visual_state"]["active_entities"] == ["train", "bridge"]
    assert p["visual_state"]["action"] == "train_run"


# issue #19 P0: an empty DSL does not crash, produces a valid empty structure.
def test_to_spec_dict_empty_dsl():
    dsl = FusionSocraticDSL(subject="math")
    spec = dsl.to_spec_dict()
    assert spec["meta"]["visual_type"] == "flow_card"
    assert spec["meta"]["fallback_type"] == "tape_diagram"
    assert spec["meta"]["grade"] == 5.0
    assert spec["parameters"] == {}
    assert spec["entities"] == []
    assert spec["pipeline"] == []


# issue #19 P0: visual_type not in the whitelist → flow_card fallback.
def test_to_spec_dict_invalid_visual_type_falls_back():
    dsl = FusionSocraticDSL(
        subject="math",
        meta={"visual_type": "bogus", "fallback_type": "bogus_fb"},
    )
    meta = dsl.to_spec_dict()["meta"]
    assert meta["visual_type"] == "flow_card"
    assert meta["fallback_type"] == "tape_diagram"


# issue #19 P0: to_spec_dict output passes the spec DSL v3.0 JSON Schema validation.
#
#     fusion-core SOCRATIC_DSL_V3_SCHEMA inlined (the 3.11 venv cannot install
#     fusion-core 3.12).
def test_to_spec_dict_passes_jsonschema():
    try:
        import jsonschema
    except ImportError:
        pytest.skip("jsonschema not installed")

    schema = {
        "type": "object",
        "required": ["meta", "parameters", "entities", "pipeline"],
        "additionalProperties": False,
        "properties": {
            "meta": {
                "type": "object",
                "required": ["id", "grade", "topic", "visual_type", "fallback_type"],
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string"},
                    "grade": {"type": "number"},
                    "topic": {"type": "string"},
                    "visual_type": {"type": "string"},
                    "fallback_type": {"type": "string"},
                },
            },
            "parameters": {"type": "object"},
            "entities": {"type": "array"},
            "pipeline": {"type": "array"},
        },
    }
    dsl = _build_full_dsl()
    spec = dsl.to_spec_dict()
    validator = jsonschema.Draft202012Validator(schema)
    errors = list(validator.iter_errors(spec))
    assert errors == [], f"spec DSL v3.0 schema validation failed: {errors}"
