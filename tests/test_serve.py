"""Fusion-K12-Teacher FastAPI serve 测试。"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from fusion_k12_teacher.assessment import AssessmentEngine
from fusion_k12_teacher.content import ContentGenerator
from fusion_k12_teacher.curriculum import CurriculumEngine
from fusion_k12_teacher.personalization import PersonalizationEngine
from fusion_k12_teacher.serve import app
from fusion_k12_teacher.subjects import SubjectExpert

MOCK_LESSON_PLAN = '{"title": "分数入门", "objectives": ["理解分数"], "materials": ["课本"], "procedures": [{"step": 1, "activity": "导入"}], "assessment": "提问", "homework": "练习"}'
MOCK_MATH_GRADE = '{"score": 10, "total": 10, "correct": true, "feedback": "正确", "mistakes": []}'
MOCK_CONCEPT = '{"simple_explanation": "分数表示部分", "example": "半个苹果"}'
MOCK_LEARNING_PATH = '{"goals": ["掌握分数"], "units": [{"title": "分数入门", "duration": "2周"}], "prerequisites": ["整数"], "estimated_duration": "4周"}'
MOCK_WORKSHEET = '{"title": "分数练习", "instructions": "认真答题", "sections": [{"title": "选择题"}], "answer_key": "答案"}'


def _mock_chat(response_text):
    async def chat(messages, temperature=0.7, max_tokens=4096):
        return response_text
    return chat


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
    # TEST-1: 保存原值, 测试后还原, 避免单例污染跨模块
    from fusion_k12_teacher import serve as srv
    saved = {
        "mlx_client": srv.mlx_client,
        "curriculum_engine": srv.curriculum_engine,
        "assessment_engine": srv.assessment_engine,
        "subject_expert": srv.subject_expert,
        "personalization_engine": srv.personalization_engine,
        "content_generator": srv.content_generator,
        "api_key": srv._API_KEY,
        "ready": srv._ready,
        "allowed_dirs": list(srv._ALLOWED_DATA_DIRS),
    }
    # SRV-1: 受保护端点 fail-closed, 测试需注入 key
    srv._API_KEY = "test-key"
    # SRV-4: 模拟 lifespan 就绪, 否则 _ready=False 拦截所有请求返 503
    srv._ready = True
    # TEST-3: ASGITransport 不触发 lifespan, 显式初始化允许目录, 覆盖路径校验
    srv._init_allowed_dirs()
    srv.mlx_client = type("M", (), {"chat": _mock_chat(MOCK_LESSON_PLAN)})()
    srv.curriculum_engine = CurriculumEngine(srv.mlx_client)
    srv.assessment_engine = AssessmentEngine(srv.mlx_client)
    srv.subject_expert = SubjectExpert(srv.mlx_client)
    srv.personalization_engine = PersonalizationEngine(srv.mlx_client)
    srv.content_generator = ContentGenerator(srv.mlx_client)
    yield
    for k, v in saved.items():
        if k == "allowed_dirs":
            srv._ALLOWED_DATA_DIRS = v
        else:
            setattr(srv, k, v)


class TestHealth:
    @pytest.mark.asyncio
    async def test_health(self, client):
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["version"] == "1.0.7"


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
        assert "simple_explanation" in data or "concept" in data


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


class TestPathValidation:
    @pytest.mark.asyncio
    async def test_data_path_outside_allowed_rejected(self, client):
        # TEST-3: data_path 越界(etc/passwd)须被 _check_allowed_path 拦截返 400
        from fusion_k12_teacher import serve as srv
        assert srv._ALLOWED_DATA_DIRS, "允许目录未初始化, 路径校验零覆盖"
        resp = await client.post("/api/analytics/class-profile", json={
            "class_id": "C1", "subject": "数学", "grade": "3",
            "data_path": "/etc/passwd",
        })
        assert resp.status_code == 400


class TestGameFailure:
    @pytest.mark.asyncio
    async def test_game_generation_failure_returns_502(self, client):
        # SRV-8: game 生成失败含 error 字段, 不再静默 200 空对象, 须返 502
        from fusion_k12_teacher import serve as srv
        # SRV-8: 须触发引擎解析失败路径(L201 返 {"error":...}), 非可解析 dict
        srv.content_generator.mlx.chat = _mock_chat("无法解析的非 JSON 文本")
        resp = await client.post("/api/content/generate", json={
            "topic": "分数", "grade": "3", "style": "game",
        })
        assert resp.status_code == 502


class TestNotReady:
    @pytest.mark.asyncio
    async def test_not_ready_returns_503(self, client):
        # SRV-4: _ready=False 时受保护端点须返 503, 不让 None 引擎崩 500
        from fusion_k12_teacher import serve as srv
        srv._ready = False
        resp = await client.post("/api/curriculum/plan", json={
            "grade": "3", "subject": "数学", "topic": "分数",
        })
        assert resp.status_code == 503
        srv._ready = True
