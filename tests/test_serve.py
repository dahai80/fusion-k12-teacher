"""Fusion-K12-Teacher FastAPI serve 测试。"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from fusion_k12_teacher.serve import app
from fusion_k12_teacher.curriculum import CurriculumEngine
from fusion_k12_teacher.assessment import AssessmentEngine
from fusion_k12_teacher.subjects import SubjectExpert
from fusion_k12_teacher.personalization import PersonalizationEngine
from fusion_k12_teacher.content import ContentGenerator


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
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture(autouse=True)
def mock_engines():
    from fusion_k12_teacher import serve as srv
    srv.mlx_client = type("M", (), {"chat": _mock_chat(MOCK_LESSON_PLAN)})()
    srv.curriculum_engine = CurriculumEngine(srv.mlx_client)
    srv.assessment_engine = AssessmentEngine(srv.mlx_client)
    srv.subject_expert = SubjectExpert(srv.mlx_client)
    srv.personalization_engine = PersonalizationEngine(srv.mlx_client)
    srv.content_generator = ContentGenerator(srv.mlx_client)


class TestHealth:
    @pytest.mark.asyncio
    async def test_health(self, client):
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["version"] == "0.2.0"


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
            "question": "分数", "grade": "3",
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
