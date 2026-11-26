# Fusion-K12-Teacher FastAPI serve tests.

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from fusion_k12_teacher.serve import app

# i18n: user-facing (mock LLM payloads below are Chinese product content)
MOCK_LESSON_PLAN = '{"title": "分数入门", "objectives": ["理解分数"], "materials": ["课本"], "procedures": [{"step": 1, "activity": "导入"}], "assessment": "提问", "homework": "练习"}'
MOCK_MATH_GRADE = '{"score": 10, "total": 10, "correct": true, "feedback": "正确", "mistakes": []}'
MOCK_CONCEPT = '{"simple_explanation": "分数表示部分", "example": "半个苹果"}'
MOCK_LEARNING_PATH = '{"goals": ["掌握分数"], "units": [{"title": "分数入门", "duration": "2周"}], "prerequisites": ["整数"], "estimated_duration": "4周"}'
MOCK_WORKSHEET = '{"title": "分数练习", "instructions": "认真答题", "sections": [{"title": "选择题"}], "answer_key": "答案"}'


def _mock_chat(response_text):
    async def chat(messages, temperature=0.7, max_tokens=4096, **kwargs):
        return response_text
    return chat


async def _mock_list_models(self=None):
    # P1-10: the health endpoint probes list_models, tests must provide the mock, otherwise AttributeError→503.
    # Function attributes on type() instances bind as methods (implicit self), so accept self explicitly.
    return [{"id": "Qwen3.5-9B-4bit"}]


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test",
        headers={"X-API-Key": "test-key"},
    ) as ac:
        yield ac


@pytest.fixture(autouse=True)
def mock_engines():
    # TEST-1: save original values, restore after tests, avoid singleton pollution across modules
    import os

    from fusion_k12_teacher import serve as srv
    from fusion_k12_teacher.engines import build_engines
    from fusion_k12_teacher.safety import ContentFilter, SensitiveWordList
    saved = {
        "mlx_client": srv.mlx_client,
        "curriculum_engine": srv.curriculum_engine,
        "assessment_engine": srv.assessment_engine,
        "subject_expert": srv.subject_expert,
        "personalization_engine": srv.personalization_engine,
        "content_generator": srv.content_generator,
        "differentiation_engine": srv.differentiation_engine,
        "standards_query": srv.standards_query,
        "standards_loader": srv.standards_loader,
        "analytics_engine": srv.analytics_engine,
        "content_filter": srv.content_filter,
        "sensitive_wordlist": srv.sensitive_wordlist,
        # R1: API key is read from env per request — save/restore the env var rather than a module constant
        "api_key_env": os.environ.get("FUSION_K12_API_KEY"),
        "ready": srv._ready,
        "allowed_dirs": list(srv._ALLOWED_DATA_DIRS),
        "standards_aligner": srv.standards_aligner,
        "subject_registry": srv.subject_registry,
        "lesson_scripter": srv.lesson_scripter,
        "packager": srv.packager,
        "session_manager": srv.session_manager,
    }
    # SRV-1: protected endpoints are fail-closed, tests must inject a key
    # R1: require_api_key reads the FUSION_K12_API_KEY env per request — inject into os.environ
    os.environ["FUSION_K12_API_KEY"] = "test-key"
    # SRV-4: simulate lifespan readiness, otherwise _ready=False intercepts all requests with 503
    srv._ready = True
    # TEST-3: ASGITransport does not trigger lifespan — initialize allowed dirs explicitly to cover path validation
    srv._init_allowed_dirs()
    # TEST-5: build the full engine bundle (analytics/differentiation/standards included), not just the 6 engines
    srv.mlx_client = type("M", (), {
        "chat": _mock_chat(MOCK_LESSON_PLAN),
        "model": "",
        "list_models": _mock_list_models,
    })()
    bundle = build_engines(mlx=srv.mlx_client)
    srv.curriculum_engine = bundle.curriculum
    srv.assessment_engine = bundle.assessment
    srv.subject_expert = bundle.subjects
    srv.personalization_engine = bundle.personalization
    srv.content_generator = bundle.content
    srv.differentiation_engine = bundle.differentiation
    srv.standards_query = bundle.standards_query
    srv.standards_loader = bundle.standards_loader
    # P3: the new align/coverage routes depend on standards_aligner — the fixture must inject it
    from fusion_k12_teacher.standards import StandardsAligner
    srv.standards_aligner = StandardsAligner(query=bundle.standards_query)
    srv.analytics_engine = bundle.analytics
    srv.content_filter = ContentFilter()
    srv.sensitive_wordlist = SensitiveWordList()
    srv.subject_registry = bundle.subject_registry
    from fusion_k12_teacher.classroom import (
        ClassroomStore,
        LessonScripter,
        Packager,
        SessionManager,
    )
    _store = ClassroomStore(db_path="/tmp/test-k12-classroom.db")
    srv.lesson_scripter = LessonScripter(srv.mlx_client)
    srv.packager = Packager(_store)
    srv.session_manager = SessionManager(_store)
    yield
    for k, v in saved.items():
        if k == "allowed_dirs":
            srv._ALLOWED_DATA_DIRS = v
        elif k == "api_key_env":
            # R1: restore the FUSION_K12_API_KEY env (None → del, otherwise set back to the original value)
            if v is None:
                os.environ.pop("FUSION_K12_API_KEY", None)
            else:
                os.environ["FUSION_K12_API_KEY"] = v
        else:
            setattr(srv, k, v)


class TestHealth:
    @pytest.mark.asyncio
    async def test_health(self, client):
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["version"] == "2.2.8"


# i18n: user-facing (request fixture data below uses Chinese sample subjects/topics)
class TestCurriculumPlan:
    @pytest.mark.asyncio
    async def test_curriculum_plan(self, client):
        from fusion_k12_teacher import serve as srv
        srv.mlx_client.chat = _mock_chat(MOCK_LESSON_PLAN)
        srv.curriculum_engine.mlx.chat = _mock_chat(MOCK_LESSON_PLAN)
        resp = await client.post("/api/curriculum/plan", json={
            "grade": "3", "subject": "数学", "topic": "分数",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "title" in data


# i18n: user-facing (request fixture data below uses Chinese sample content)
class TestAssessmentGrade:
    @pytest.mark.asyncio
    async def test_assessment_grade(self, client):
        from fusion_k12_teacher import serve as srv
        srv.assessment_engine.mlx.chat = _mock_chat(MOCK_MATH_GRADE)
        resp = await client.post("/api/assessment/grade", json={
            "question": "2+2=?", "answer": "4", "standard": "4",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "score" in data
        assert "total" in data


# i18n: user-facing (request fixture data below uses Chinese sample content)
class TestSubjectExplain:
    @pytest.mark.asyncio
    async def test_subject_explain(self, client):
        from fusion_k12_teacher import serve as srv
        srv.subject_expert.mlx.chat = _mock_chat(MOCK_CONCEPT)
        resp = await client.post("/api/subject/explain", json={
            "subject": "数学", "grade": "3", "concept": "分数",
        })
        assert resp.status_code == 200
        data = resp.json()
        # TEST-4: assert only the success field — `or "concept"` would accept an engine failure degraded into a pass
        assert "simple_explanation" in data


# i18n: user-facing (request fixture data below uses Chinese sample content)
class TestPersonalizePath:
    @pytest.mark.asyncio
    async def test_personalize_path(self, client):
        from fusion_k12_teacher import serve as srv
        srv.personalization_engine.mlx.chat = _mock_chat(MOCK_LEARNING_PATH)
        resp = await client.post("/api/personalize/path", json={
            "student_id": "张三", "progress": {"grade": "3", "subject": "数学", "goal": "掌握分数"},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["student_id"] == "张三"


# i18n: user-facing (request fixture data and mock payloads below use Chinese sample content)
class TestContentGenerate:
    @pytest.mark.asyncio
    async def test_content_generate_worksheet(self, client):
        from fusion_k12_teacher import serve as srv
        srv.content_generator.mlx.chat = _mock_chat(MOCK_WORKSHEET)
        resp = await client.post("/api/content/generate", json={
            "topic": "分数", "grade": "3", "style": "interactive",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "worksheet"

    @pytest.mark.asyncio
    async def test_content_generate_flashcards(self, client):
        from fusion_k12_teacher import serve as srv
        srv.content_generator.mlx.chat = _mock_chat('[{"front": "1/2", "back": "0.5"}]')
        resp = await client.post("/api/content/generate", json={
            "topic": "分数", "grade": "3", "style": "flashcards",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "flashcards"

    @pytest.mark.asyncio
    async def test_content_generate_slides(self, client):
        from fusion_k12_teacher import serve as srv
        srv.content_generator.mlx.chat = _mock_chat('[{"slide_number": 1, "title": "引言"}]')
        resp = await client.post("/api/content/generate", json={
            "topic": "分数", "grade": "3", "style": "slides",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "slides"

    @pytest.mark.asyncio
    async def test_content_generate_game(self, client):
        from fusion_k12_teacher import serve as srv
        srv.content_generator.mlx.chat = _mock_chat('{"title": "分数大冒险", "type": "board", "objective": "掌握分数"}')
        resp = await client.post("/api/content/generate", json={
            "topic": "分数", "grade": "3", "style": "game",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "game"


# i18n: user-facing (request fixture data below uses Chinese sample content)
class TestPathValidation:
    @pytest.mark.asyncio
    async def test_data_path_outside_allowed_rejected(self, client):
        # TEST-3: out-of-bounds data_path (etc/passwd) must be intercepted by _check_allowed_path with 400
        from fusion_k12_teacher import serve as srv
        assert srv._ALLOWED_DATA_DIRS, "Allowed dirs not initialized, path validation has zero coverage"
        resp = await client.post("/api/analytics/class-profile", json={
            "class_id": "C1", "subject": "数学", "grade": "3",
            "data_path": "/etc/passwd",
        })
        assert resp.status_code == 400


# i18n: user-facing (request fixture data below uses Chinese sample content)
class TestGameFailure:
    @pytest.mark.asyncio
    async def test_game_generation_failure_returns_502(self, client):
        # SRV-8: game generation failure includes an error field, no more silent 200 empty object — must return 502
        from fusion_k12_teacher import serve as srv
        # SRV-8: must trigger the engine parse-failure path (L201 returns {"error":...}), not a parseable dict
        # i18n: user-facing
        srv.content_generator.mlx.chat = _mock_chat("无法解析的非 JSON 文本")
        resp = await client.post("/api/content/generate", json={
            "topic": "分数", "grade": "3", "style": "game",
        })
        assert resp.status_code == 502


# i18n: user-facing (request fixture data below uses Chinese sample content)
class TestNotReady:
    @pytest.mark.asyncio
    async def test_not_ready_returns_503(self, client):
        # SRV-4: with _ready=False, protected endpoints must return 503 instead of None engines crashing with 500
        from fusion_k12_teacher import serve as srv
        srv._ready = False
        resp = await client.post("/api/curriculum/plan", json={
            "grade": "3", "subject": "数学", "topic": "分数",
        })
        assert resp.status_code == 503
        srv._ready = True


# ══════════════════════════════════════════════════════════════════════════════
# TEST-5: cover previously untested endpoints — analytics/standards/agent/safety/desensitize/diff/auth
# ══════════════════════════════════════════════════════════════════════════════

# i18n: user-facing (request fixture data below uses Chinese sample subjects/topics)
class TestStandardsEndpoints:
    @pytest.mark.asyncio
    async def test_standards_list(self, client):
        # R5: read endpoints also require auth (sensitive wordlist/agent history/standards), client fixture carries X-API-Key by default
        resp = await client.get("/api/standards/list", params={"subject": "数学", "grade": "3"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] > 0
        assert "knowledge_points" in data

    @pytest.mark.asyncio
    async def test_standards_query(self, client):
        resp = await client.post("/api/standards/query", json={
            "subject": "数学", "grade": "3", "topic": "分数",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 0

    @pytest.mark.asyncio
    async def test_standards_align(self, client):
        # P3: new standards alignment route
        resp = await client.post("/api/standards/align", json={
            "subject": "数学", "grade": "3", "topic": "分数",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["subject"] == "数学"
        assert "knowledge_points" in data
        assert "must_cover" in data

    @pytest.mark.asyncio
    async def test_standards_coverage(self, client):
        # P3: new standards coverage report route
        resp = await client.post("/api/standards/coverage", json={
            "subject": "数学", "grade": "3", "objectives": ["理解分数的意义"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "coverage_ratio" in data
        assert "missing_points" in data

    @pytest.mark.asyncio
    async def test_standards_remediate(self, client):
        # Remediation plan for missing knowledge points — LLM mock returns structured JSON, verify the success path
        from fusion_k12_teacher import serve as srv
        # i18n: user-facing
        mock_resp = '{"strategies":["数形结合"],"exercises":[{"topic":"万以内数","type":"填空","difficulty":"easy","count":3}],"timeline":"1周","estimated_duration":"20分钟"}'
        saved_chat = srv.mlx_client.chat
        srv.mlx_client.chat = _mock_chat(mock_resp)
        try:
            resp = await client.post("/api/standards/remediate", json={
                "subject": "数学", "grade": "3", "topic": "分数",
                "missing_points": ["math-g3-na-01"],
            })
        finally:
            srv.mlx_client.chat = saved_chat
        assert resp.status_code == 200
        data = resp.json()
        assert data["subject"] == "数学"
        assert isinstance(data["missing_points"], list)
        assert len(data["missing_points"]) >= 1
        assert data["strategies"] == ["数形结合"]
        assert data["exercises"][0]["topic"] == "万以内数"
        assert data["estimated_duration"] == "20分钟"

    @pytest.mark.asyncio
    async def test_standards_remediate_degrade(self, client):
        # LLM returns non-JSON → graceful degradation, non-empty error + empty strategies
        from fusion_k12_teacher import serve as srv
        saved_chat = srv.mlx_client.chat
        srv.mlx_client.chat = _mock_chat("not-a-json")
        try:
            resp = await client.post("/api/standards/remediate", json={
                "subject": "数学", "grade": "3", "topic": "分数",
                "missing_points": ["math-g3-na-01"],
            })
        finally:
            srv.mlx_client.chat = saved_chat
        assert resp.status_code == 200
        data = resp.json()
        assert data["error"]
        assert data["strategies"] == []


# i18n: user-facing (request fixture data below uses Chinese sample subjects/topics)
class TestAnalyticsEndpoints:
    @pytest.mark.asyncio
    async def test_analytics_class_profile(self, client):
        # No data_path → empty assessments, build_class_profile degrades gracefully to the default profile
        resp = await client.post("/api/analytics/class-profile", json={
            "class_id": "C1", "subject": "数学", "grade": "3",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["class_id"] == "C1"

    @pytest.mark.asyncio
    async def test_analytics_error_analysis(self, client):
        resp = await client.post("/api/analytics/error-analysis", json={
            "subject": "数学", "grade": "3",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data and "errors" in data

    @pytest.mark.asyncio
    async def test_analytics_upload_then_path_traversal(self, client):
        # Normal upload
        resp = await client.post("/api/analytics/upload", json={
            "data": [{"student_id": "S1", "subject": "数学", "grade": "3"}], "format": "json",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["accepted"] == 1
        assert "filename" in data  # SRV-10: filename only, never leaks the absolute path
        # Path traversal → 400 (AGT-2: shares the validate_data_path whitelist)
        bad = await client.post("/api/agent/run", json={
            "task_id": "weekly_summary", "subject": "数学", "grade": "3",
            "data_path": "/etc/passwd",
        })
        assert bad.status_code == 400


class TestAgentEndpoints:
    @pytest.mark.asyncio
    async def test_agent_tasks(self, client):
        resp = await client.get("/api/agent/tasks")
        assert resp.status_code == 200
        data = resp.json()
        assert "predefined" in data and "registered" in data

    @pytest.mark.asyncio
    async def test_agent_history(self, client):
        resp = await client.get("/api/agent/history", params={"limit": 5})
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data and "history" in data


# i18n: user-facing (request fixture data below uses Chinese sample content)
class TestSafetyEndpoints:
    @pytest.mark.asyncio
    async def test_safety_check(self, client):
        # check_text rule layer does not depend on the LLM, normal text should return 200
        resp = await client.post("/api/safety/check", json={
            "text": "这是一段正常教学内容", "grade": "3",
        })
        assert resp.status_code == 200
        assert "is_safe" in resp.json()

    @pytest.mark.asyncio
    async def test_safety_filter(self, client):
        resp = await client.post("/api/safety/filter", json={"text": "正常文本"})
        assert resp.status_code == 200
        assert "filtered_text" in resp.json()

    @pytest.mark.asyncio
    async def test_safety_wordlist_list(self, client):
        resp = await client.get("/api/safety/wordlist")
        assert resp.status_code == 200
        assert "count" in resp.json()

    @pytest.mark.asyncio
    async def test_read_endpoints_require_auth(self):
        # R5: 4 read endpoints without X-API-Key must return 401 — wordlist/agent history/task list/standards must not be readable unauthorized
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as noauth:
            for path in ("/api/safety/wordlist", "/api/agent/tasks", "/api/agent/history", "/api/standards/list"):
                resp = await noauth.get(path)
                assert resp.status_code == 401, f"{path} should be rejected without auth"


# i18n: user-facing (request fixture data below uses Chinese sample names)
class TestDesensitizeEndpoint:
    @pytest.mark.asyncio
    async def test_desensitize_anonymize(self, client):
        resp = await client.post("/api/desensitize/anonymize", json={
            "records": [{"name": "张三", "phone": "13800138000"}],
            "name_mode": "id", "id_prefix": "S",
        })
        assert resp.status_code == 200
        data = resp.json()
        # Returns {"result": {original_count, anonymized_count, ...}}
        assert "result" in data and data["result"]["anonymized_count"] == 1


# i18n: user-facing (request fixture data below uses Chinese sample content)
class TestDifferentiationEndpoint:
    @pytest.mark.asyncio
    async def test_curriculum_plan_diff(self, client):
        from fusion_k12_teacher import serve as srv
        # i18n: user-facing
        srv.differentiation_engine.mlx.chat = _mock_chat(
            '{"explanation": "分层讲解", "examples": ["例1"], "exercises": [], "hints": [], "extension": ""}'
        )
        resp = await client.post("/api/curriculum/plan-diff", json={
            "subject": "数学", "grade": "3", "topic": "分数", "duration": 45,
        })
        assert resp.status_code == 200
        # E3: tiered content moved to the layers dict, no more top-level struggling field
        assert "struggling" in resp.json()["layers"]


# i18n: user-facing (request fixture data below uses Chinese sample content)
class TestAuthEnforcement:
    # TEST-5: auth had zero coverage — protected endpoints must 401 on missing/wrong key, not rely on _ready alone
    @pytest.mark.asyncio
    async def test_missing_api_key_rejected(self):
        # Bare client without X-API-Key
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post("/api/curriculum/plan", json={
                "grade": "3", "subject": "数学", "topic": "分数",
            })
            assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_wrong_api_key_rejected(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test",
            headers={"X-API-Key": "wrong-key"},
        ) as ac:
            resp = await ac.post("/api/curriculum/plan", json={
                "grade": "3", "subject": "数学", "topic": "分数",
            })
            assert resp.status_code == 401


# M3-T19: graceful drain shutdown — reject new requests during drain, wait for in-flight to reach zero.
class TestGracefulDrain:

    @pytest.mark.asyncio
    async def test_draining_rejects_new(self, client):
        import fusion_k12_teacher.serve as srv
        srv._draining = True
        srv._ready = True
        try:
            resp = await client.post("/api/curriculum/plan", json={
                "grade": "3", "subject": "数学", "topic": "分数",
            })
            assert resp.status_code == 503
            assert resp.headers.get("Connection") == "close"
        finally:
            srv._draining = False

    @pytest.mark.asyncio
    async def test_drain_inflight_zero_immediate(self):
        import asyncio

        import fusion_k12_teacher.serve as srv
        from fusion_k12_teacher.serve import _drain_inflight
        srv._inflight = 0
        srv._inflight_zero = asyncio.Event()
        await asyncio.wait_for(_drain_inflight(), timeout=2)
        assert srv._draining is True
        srv._draining = False

    @pytest.mark.asyncio
    async def test_drain_inflight_waits_then_completes(self):
        import asyncio

        import fusion_k12_teacher.serve as srv
        from fusion_k12_teacher.serve import _drain_inflight
        srv._inflight = 1
        srv._inflight_zero = asyncio.Event()

        async def release_after():
            await asyncio.sleep(0.1)
            srv._inflight = 0
            srv._inflight_zero.set()

        await asyncio.gather(_drain_inflight(), release_after())
        assert srv._draining is True
        srv._draining = False

    @pytest.mark.asyncio
    async def test_drain_timeout_forces_close(self, monkeypatch):
        import asyncio

        import fusion_k12_teacher.serve as srv
        from fusion_k12_teacher.serve import _drain_inflight
        monkeypatch.setenv("FUSION_K12_DRAIN_TIMEOUT", "0.2")
        srv._inflight = 1
        srv._inflight_zero = asyncio.Event()
        await _drain_inflight()
        assert srv._draining is True
        srv._draining = False


# M3-T13/T15: audit middleware + export endpoints.
class TestAuditServe:

    @pytest.mark.asyncio
    async def test_audit_trace_id_header(self, client):
        resp = await client.post("/api/curriculum/plan", json={
            "grade": "3", "subject": "数学", "topic": "分数",
        })
        assert resp.headers.get("X-Trace-Id")

    @pytest.mark.asyncio
    async def test_audit_export_admin_key(self, client):
        import os

        import fusion_k12_teacher.serve as srv
        os.environ["FUSION_K12_ADMIN_API_KEY"] = "admin-secret"
        orig = getattr(srv.scheduler, "_repo", None)

        class _FakeRepo:
            def load_audit(self, since_ts="", limit=1000):
                return [{"route": "/api/x", "status": 200, "ts": "2026-01-01T00:00:00"}]

        srv.scheduler._repo = _FakeRepo()
        try:
            resp = await client.get(
                "/api/audit/export?format=json&limit=10",
                headers={"X-API-Key": "admin-secret"},
            )
            assert resp.status_code == 200
        finally:
            srv.scheduler._repo = orig
            os.environ.pop("FUSION_K12_ADMIN_API_KEY", None)

    @pytest.mark.asyncio
    async def test_audit_export_wrong_key_rejected(self, client):
        import os
        os.environ["FUSION_K12_ADMIN_API_KEY"] = "admin-secret"
        try:
            resp = await client.get(
                "/api/audit/export", headers={"X-API-Key": "wrong"},
            )
            assert resp.status_code == 403
        finally:
            os.environ.pop("FUSION_K12_ADMIN_API_KEY", None)


# M3-T16: metrics endpoint.
class TestMetricsServe:

    @pytest.mark.asyncio
    async def test_metrics_endpoint_admin(self, client):
        import os
        os.environ["FUSION_K12_ADMIN_API_KEY"] = "admin-secret"
        try:
            resp = await client.get("/api/metrics", headers={"X-API-Key": "admin-secret"})
            assert resp.status_code == 200
            assert "k12_request_total" in resp.text
        finally:
            os.environ.pop("FUSION_K12_ADMIN_API_KEY", None)

    @pytest.mark.asyncio
    async def test_metrics_wrong_key_rejected(self, client):
        import os
        os.environ["FUSION_K12_ADMIN_API_KEY"] = "admin-secret"
        try:
            resp = await client.get("/api/metrics", headers={"X-API-Key": "nope"})
            assert resp.status_code == 403
        finally:
            os.environ.pop("FUSION_K12_ADMIN_API_KEY", None)
