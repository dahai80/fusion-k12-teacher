"""学科课程平台 REST 路由测试 — 平台-内容解耦, subject 参数分发。"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from fusion_k12_teacher.serve import app

MOCK_SCRIPT = '{"global_variables": {"L_train": {"label": "车长", "unit": "m", "value": 200, "is_unknown": false}}, "steps": [{"step_id": "step1", "step_title": "观察", "phase": "Engage", "speech_narration": "看火车", "landmarks": [{"timeOffsetMs": 0, "progressRatio": 0.0, "latexHighlightVar": "L_train"}], "animation": {"start_ratio": 0.0, "end_ratio": 0.3}, "checkpoint": {"id": "cp1", "type": "multiple_choice", "prompt": "p", "options": [{"id": "a", "label": "A", "is_correct": true, "feedback": "ok"}], "hints": ["h"], "on_error_action": "rewind", "difficulty_layer": "B"}}]}'
MOCK_SCENE = '{"scenario": "train_crossing_bridge", "entities": {"bridge": {"length": 800, "label": "大桥"}, "train": {"length": 200, "speed": 20, "label": "火车"}}, "key_milestones": [{"time_ratio": 0.0, "label": "start", "event": "start"}], "question_focus": "t", "misconception_hint": "忘加车长"}'


def _mock_chat(response_text):
    async def chat(self, messages, temperature=0.7, max_tokens=4096):
        return response_text
    return chat


async def _mock_list_models(self=None):
    return [{"id": "Qwen3.5-9B-4bit"}]


@pytest.fixture
async def client():
    import os

    from fusion_k12_teacher import serve as srv
    from fusion_k12_teacher.engines import build_engines
    from fusion_k12_teacher.safety import ContentFilter, SensitiveWordList
    saved = {
        "mlx_client": srv.mlx_client,
        "content_filter": srv.content_filter,
        "sensitive_wordlist": srv.sensitive_wordlist,
        "subject_registry": srv.subject_registry,
        "api_key_env": os.environ.get("FUSION_K12_API_KEY"),
        "ready": srv._ready,
        "standards_query": srv.standards_query,
        "lesson_scripter": srv.lesson_scripter,
        "packager": srv.packager,
        "session_manager": srv.session_manager,
    }
    os.environ["FUSION_K12_API_KEY"] = "test-key"
    srv._ready = True
    srv.mlx_client = type("M", (), {"chat": _mock_chat(MOCK_SCRIPT), "model": "", "list_models": _mock_list_models})()
    bundle = build_engines(mlx=srv.mlx_client)
    srv.content_filter = ContentFilter()
    srv.sensitive_wordlist = SensitiveWordList()
    srv.subject_registry = bundle.subject_registry
    srv.standards_query = bundle.standards_query
    from fusion_k12_teacher.classroom import (
        ClassroomStore,
        LessonScripter,
        Packager,
        SessionManager,
    )
    _store = ClassroomStore(db_path="/tmp/test-k12-classroom-course.db")
    srv.lesson_scripter = LessonScripter(srv.mlx_client)
    srv.packager = Packager(_store)
    srv.session_manager = SessionManager(_store)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers={"X-API-Key": "test-key"}) as ac:
        yield ac
    for k, v in saved.items():
        if k == "api_key_env":
            if v is None:
                os.environ.pop("FUSION_K12_API_KEY", None)
            else:
                os.environ["FUSION_K12_API_KEY"] = v
        else:
            setattr(srv, k, v)


class TestCourseSubjects:
    @pytest.mark.asyncio
    async def test_list_subjects(self, client):
        r = await client.get("/api/course/subjects")
        assert r.status_code == 200
        data = r.json()
        ids = [s["subject_id"] for s in data["subjects"]]
        assert "math" in ids

    @pytest.mark.asyncio
    async def test_unknown_subject_404(self, client):
        r = await client.get("/api/course/physics/graph/nodes")
        assert r.status_code == 404


class TestCourseGraph:
    @pytest.mark.asyncio
    async def test_graph_nodes(self, client):
        r = await client.get("/api/course/math/graph/nodes", params={"grade": "5"})
        assert r.status_code == 200
        data = r.json()
        assert data["subject"] == "math"
        assert data["count"] > 0

    @pytest.mark.asyncio
    async def test_graph_node_detail(self, client):
        r = await client.get("/api/course/math/graph/nodes", params={"grade": "1"})
        node_id = r.json()["nodes"][0]["id"]
        r2 = await client.get(f"/api/course/math/graph/node/{node_id}")
        assert r2.status_code == 200
        assert r2.json()["node"]["id"] == node_id
        assert "prerequisites_chain" in r2.json()

    @pytest.mark.asyncio
    async def test_graph_node_404(self, client):
        r = await client.get("/api/course/math/graph/node/nonexistent")
        assert r.status_code == 404


class TestCourseLessonScript:
    @pytest.mark.asyncio
    async def test_lesson_script(self, client):
        r = await client.post("/api/course/math/lesson-script", json={
            "subject": "math", "topic": "火车过桥", "grade": "5", "layer": "B",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["subject"] == "math"
        assert len(data["steps"]) >= 1
        assert data["steps"][0]["checkpoint"] is not None


class TestCourseCheckpoint:
    @pytest.mark.asyncio
    async def test_checkpoint_numeric(self, client):
        r = await client.post("/api/course/math/checkpoint", json={
            "checkpoint": {"id": "cp1", "type": "numeric_input", "expected_value": 50, "tolerance": 0.01},
            "student_answer": "50",
        })
        assert r.status_code == 200
        assert r.json()["correct"] is True

    @pytest.mark.asyncio
    async def test_checkpoint_expression(self, client):
        r = await client.post("/api/course/math/checkpoint", json={
            "checkpoint": {"id": "cp1", "type": "expression", "expected_expression": "(800-200)/20"},
            "student_answer": "600/20",
        })
        assert r.status_code == 200
        assert r.json()["correct"] is True


class TestCourseSceneCompile:
    @pytest.mark.asyncio
    async def test_scene_compile(self, client):
        # 换 mock 返回场景提取 JSON — 赋值到类, 保持方法绑定 (实例赋值不绑 self)
        from fusion_k12_teacher import serve as srv
        type(srv.mlx_client).chat = _mock_chat(MOCK_SCENE)
        r = await client.post("/api/course/math/scene-compile", json={
            "problem_text": "200米火车20米每秒过800米大桥求时间",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["subject"] == "math"
        assert data["template_type"] == "train_crossing_bridge"
        assert data["verified"] is True
        assert data["timeline"]["total_time"] == 50.0


class TestCourseErrorAttribution:
    @pytest.mark.asyncio
    async def test_error_attribution(self, client):
        r = await client.get("/api/course/math/graph/nodes", params={"grade": "5"})
        node_id = r.json()["nodes"][0]["id"]
        r2 = await client.post("/api/course/math/error-attribution", json={
            "node_id": node_id, "max_depth": 2,
        })
        assert r2.status_code == 200
        assert "attribution_path" in r2.json()


class TestCourseMastery:
    @pytest.mark.asyncio
    async def test_mastery_empty(self, client):
        r = await client.get("/api/course/math/mastery/s1")
        assert r.status_code == 200
        assert r.json()["profile"] == {}


class TestCourseProblemBank:
    @pytest.mark.asyncio
    async def test_problem_bank_list(self, client):
        r = await client.get("/api/course/math/problem-bank")
        assert r.status_code == 200
        data = r.json()
        assert data["subject"] == "math"
        assert data["count"] == 134
        assert len(data["problems"]) == 134
        assert data["manifest"]["count"] == 134

    @pytest.mark.asyncio
    async def test_problem_bank_filter(self, client):
        r = await client.get("/api/course/math/problem-bank", params={"difficulty_layer": "A"})
        assert r.status_code == 200
        for p in r.json()["problems"]:
            assert p["difficulty_layer"] == "A"

    @pytest.mark.asyncio
    async def test_problem_detail(self, client):
        r = await client.get("/api/course/math/problem-bank/tb-ex-01")
        assert r.status_code == 200
        p = r.json()["problem"]
        assert p["template_id"] == "train_crossing_bridge"
        assert p["expected"]["t"] == 50.0

    @pytest.mark.asyncio
    async def test_problem_detail_404(self, client):
        r = await client.get("/api/course/math/problem-bank/nonexistent")
        assert r.status_code == 404
