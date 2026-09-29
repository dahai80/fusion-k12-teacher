"""课堂模块测试 — E1-E6 K1 文字版 (mock LLM)。"""

from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient

from fusion_k12_teacher.serve import app

MOCK_SCRIPT_JSON = '''{"pages": [{"page_index": 0, "title": "导入", "narration": "今天学分数。想想切披萨怎么平分?", "slide_content": "分数引入", "question_point": {"prompt": "1/2表示什么?", "type": "multiple_choice", "options": ["一半","两倍","三倍"], "answer": "一半", "explanation": "1/2 就是一半"}, "emotion_tag": "curious"}, {"page_index": 1, "title": "计算", "narration": "同分母相加, 分母不变分子相加。", "slide_content": "1/4+2/4=3/4", "question_point": {"prompt": "1/4+2/4=?", "type": "numeric", "answer": "0.75", "explanation": "3/4=0.75"}, "emotion_tag": "encouraging"}]}'''


def _mock_chat(response_text):
    async def chat(self, messages, temperature=0.7, max_tokens=4096):
        return response_text
    return chat


async def _mock_list_models(self=None):
    return [{"id": "Qwen3.5-9B-4bit"}]


@pytest.fixture
async def client():
    from fusion_k12_teacher import serve as srv
    from fusion_k12_teacher.engines import build_engines
    saved = {
        "mlx_client": srv.mlx_client,
        "subject_registry": srv.subject_registry,
        "api_key_env": os.environ.get("FUSION_K12_API_KEY"),
        "ready": srv._ready,
        "lesson_scripter": srv.lesson_scripter,
        "packager": srv.packager,
        "session_manager": srv.session_manager,
        "assessment_engine": srv.assessment_engine,
    }
    os.environ["FUSION_K12_API_KEY"] = "test-key"
    srv._ready = True
    srv.mlx_client = type("M", (), {"chat": _mock_chat(MOCK_SCRIPT_JSON), "model": "", "list_models": _mock_list_models})()
    bundle = build_engines(mlx=srv.mlx_client)
    srv.subject_registry = bundle.subject_registry
    srv.assessment_engine = bundle.assessment
    from fusion_k12_teacher.classroom import (
        ClassroomStore,
        LessonScripter,
        Packager,
        SessionManager,
    )
    _store = ClassroomStore(db_path="/tmp/test-k12-classroom-unit.db")
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


class TestClassroomScript:
    @pytest.mark.asyncio
    async def test_generate_script(self, client):
        r = await client.post("/api/classroom/script", json={
            "subject": "数学", "grade": "5", "topic": "分数加减",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["subject"] == "数学"
        assert len(data["pages"]) == 2
        assert data["pages"][0]["narration"]
        assert data["pages"][0]["question_point"]["prompt"]

    @pytest.mark.asyncio
    async def test_script_fallback_on_bad_llm(self, client):
        from fusion_k12_teacher import serve as srv
        type(srv.mlx_client).chat = _mock_chat("not json at all")
        r = await client.post("/api/classroom/script", json={
            "subject": "数学", "grade": "3", "topic": "乘法",
            "lesson_plan": {"sections": [{"title": "s1", "content": "c1"}]},
        })
        assert r.status_code == 200
        data = r.json()
        assert len(data["pages"]) >= 1
        assert data.get("error") or data["pages"][0]["narration"]


class TestClassroomPack:
    @pytest.mark.asyncio
    async def test_pack_and_get(self, client):
        r = await client.post("/api/classroom/pack", json={
            "subject": "数学", "grade": "5", "topic": "分数",
            "lesson_plan": {"title": "分数"}, "quiz": {"q1": "a"},
        })
        assert r.status_code == 200
        pkg = r.json()
        assert len(pkg["code"]) == 6
        assert pkg["class_id"]
        code = pkg["code"]
        r2 = await client.get(f"/api/classroom/pack/{code}")
        assert r2.status_code == 200
        manifest = r2.json()
        assert manifest["code"] == code
        assert manifest["has_quiz"] is True

    @pytest.mark.asyncio
    async def test_pack_invalid_code(self, client):
        r = await client.get("/api/classroom/pack/999999")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_list_packs(self, client):
        await client.post("/api/classroom/pack", json={"subject": "数学", "grade": "5", "topic": "t1"})
        r = await client.get("/api/classroom/packs")
        assert r.status_code == 200
        assert r.json()["count"] >= 1


class TestClassroomSession:
    @pytest.mark.asyncio
    async def test_full_flow(self, client):
        pack = (await client.post("/api/classroom/pack", json={
            "subject": "数学", "grade": "5", "topic": "分数",
            "quiz": {"q1": {"answer": "0.75"}},
        })).json()
        code = pack["code"]
        sess = (await client.post("/api/classroom/session", json={
            "code": code, "student_id": "s001",
        })).json()
        sid = sess["session"]["session_id"]
        assert sess["package"]["topic"] == "分数"
        await client.get(f"/api/classroom/session/{sid}/page/0")
        await client.get(f"/api/classroom/session/{sid}/page/1")
        ans = await client.post("/api/classroom/answer", json={
            "session_id": sid, "question_id": "q1", "student_answer": "0.75",
            "expected_answer": "0.75", "question_type": "numeric",
        })
        assert ans.status_code == 200
        assert ans.json()["correct"] is True
        finish = await client.patch(f"/api/classroom/session/{sid}/finish")
        assert finish.status_code == 200
        assert finish.json()["session"]["status"] == "finished"
        report = await client.get(f"/api/classroom/report/{sid}")
        assert report.status_code == 200
        rep = report.json()
        assert rep["quiz_stat"]["total"] == 1
        assert rep["quiz_stat"]["correct"] == 1
        assert len(rep["pages_viewed"]) == 2

    @pytest.mark.asyncio
    async def test_abandoned_no_snapshot(self, client):
        pack = (await client.post("/api/classroom/pack", json={
            "subject": "数学", "grade": "5", "topic": "x",
        })).json()
        sess = (await client.post("/api/classroom/session", json={
            "code": pack["code"], "student_id": "s002",
        })).json()
        sid = sess["session"]["session_id"]
        await client.patch(f"/api/classroom/session/{sid}/finish?abandoned=true")
        rep = await client.get(f"/api/classroom/report/{sid}")
        assert rep.status_code == 200
        data = rep.json()
        assert data["quiz_stat"] == {}
        assert data["error"]

    @pytest.mark.asyncio
    async def test_session_invalid_code(self, client):
        r = await client.post("/api/classroom/session", json={"code": "000000", "student_id": "s"})
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_multiple_choice_judge(self, client):
        pack = (await client.post("/api/classroom/pack", json={
            "subject": "数学", "grade": "5", "topic": "m",
        })).json()
        sess = (await client.post("/api/classroom/session", json={
            "code": pack["code"], "student_id": "s003",
        })).json()
        sid = sess["session"]["session_id"]
        ans = await client.post("/api/classroom/answer", json={
            "session_id": sid, "question_id": "q", "student_answer": "B",
            "expected_answer": "B", "question_type": "multiple_choice",
        })
        assert ans.json()["correct"] is True
        ans2 = await client.post("/api/classroom/answer", json={
            "session_id": sid, "question_id": "q", "student_answer": "A",
            "expected_answer": "B", "question_type": "multiple_choice",
        })
        assert ans2.json()["correct"] is False
