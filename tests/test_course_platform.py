"""课程平台抽象层测试 — 平台-内容解耦、学科注册、通用 DSL。"""

from __future__ import annotations

import pytest

from fusion_k12_teacher.course import (
    Checkpoint,
    CheckpointType,
    MasteryTracker,
    OnErrorAction,
    SceneDSL,
    SubjectNotFoundError,
    SubjectRegistry,
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
