"""FastAPI HTTP API 入口 — 暴露 5 大引擎为 REST API。"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import FastAPI
from pydantic import BaseModel, Field

from .ai_client import MLXClient
from .assessment import AssessmentEngine
from .content import ContentGenerator
from .curriculum import CurriculumEngine
from .personalization import PersonalizationEngine
from .subjects import SubjectExpert

logger = logging.getLogger(__name__)

mlx_client: MLXClient | None = None
curriculum_engine: CurriculumEngine | None = None
assessment_engine: AssessmentEngine | None = None
subject_expert: SubjectExpert | None = None
personalization_engine: PersonalizationEngine | None = None
content_generator: ContentGenerator | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global mlx_client, curriculum_engine, assessment_engine
    global subject_expert, personalization_engine, content_generator
    mlx_client = MLXClient()
    curriculum_engine = CurriculumEngine(mlx_client)
    assessment_engine = AssessmentEngine(mlx_client)
    subject_expert = SubjectExpert(mlx_client)
    personalization_engine = PersonalizationEngine(mlx_client)
    content_generator = ContentGenerator(mlx_client)
    logger.info("Fusion-K12-Teacher API started, MLXClient initialized")
    yield
    logger.info("Fusion-K12-Teacher API shutting down")


app = FastAPI(
    title="Fusion-K12-Teacher API",
    version="0.2.0",
    lifespan=lifespan,
)


# ── Request/Response Models ──

class CurriculumPlanRequest(BaseModel):
    grade: str = Field(..., description="年级")
    subject: str = Field(..., description="学科")
    topic: str = Field(..., description="主题")

class AssessmentGradeRequest(BaseModel):
    question: str = Field(..., description="题目")
    answer: str = Field(..., description="学生答案")
    standard: str = Field("", description="参考答案/评分标准")

class SubjectExplainRequest(BaseModel):
    question: str = Field(..., description="概念/问题")
    grade: str = Field("", description="年级")

class PersonalizePathRequest(BaseModel):
    student_id: str = Field(..., description="学生ID")
    progress: Dict[str, Any] = Field(default_factory=dict, description="学习进度")

class ContentGenerateRequest(BaseModel):
    topic: str = Field(..., description="主题")
    grade: str = Field("", description="年级")
    style: str = Field("interactive", description="生成风格")


# ── Health ──

@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "0.2.0"}


# ── Curriculum ──

@app.post("/api/curriculum/plan")
async def curriculum_plan(req: CurriculumPlanRequest):
    logger.info("curriculum/plan: grade=%s subject=%s topic=%s", req.grade, req.subject, req.topic)
    plan = await curriculum_engine.generate_lesson_plan(
        subject=req.subject, grade=req.grade, topic=req.topic,
    )
    return plan.to_dict()


# ── Assessment ──

@app.post("/api/assessment/grade")
async def assessment_grade(req: AssessmentGradeRequest):
    logger.info("assessment/grade: question=%s...", req.question[:30])
    result = await assessment_engine.grade_math(
        problem=req.question, answer=req.answer, solution=req.standard,
    )
    return {
        "score": result.score,
        "total": result.total,
        "percentage": result.percentage,
        "feedback": result.feedback,
        "improvements": result.improvements,
    }


# ── Subject ──

@app.post("/api/subject/explain")
async def subject_explain(req: SubjectExplainRequest):
    logger.info("subject/explain: question=%s...", req.question[:30])
    result = await subject_expert.explain_concept(
        subject=req.question, grade=req.grade or "3", concept=req.question,
    )
    return result


# ── Personalize ──

@app.post("/api/personalize/path")
async def personalize_path(req: PersonalizePathRequest):
    logger.info("personalize/path: student=%s", req.student_id)
    grade = req.progress.get("grade", "3")
    subject = req.progress.get("subject", "数学")
    goal = req.progress.get("goal", "综合提升")
    path = await personalization_engine.create_learning_path(
        student=req.student_id, grade=grade, subject=subject, goal=goal,
    )
    return {
        "student_id": path.student_id,
        "grade": path.grade,
        "subject": path.subject,
        "goals": path.goals,
        "units": path.units,
        "estimated_duration": path.estimated_duration,
        "prerequisites": path.prerequisites,
    }


# ── Content ──

@app.post("/api/content/generate")
async def content_generate(req: ContentGenerateRequest):
    logger.info("content/generate: topic=%s grade=%s style=%s", req.topic, req.grade, req.style)
    if req.style == "flashcards":
        result = await content_generator.generate_flashcards(
            subject="综合", grade=req.grade or "3", topic=req.topic,
        )
        return {"type": "flashcards", "items": result}
    elif req.style == "slides":
        result = await content_generator.generate_lesson_slides(
            subject="综合", grade=req.grade or "3", topic=req.topic,
        )
        return {"type": "slides", "items": result}
    elif req.style == "game":
        result = await content_generator.generate_educational_game(
            subject="综合", grade=req.grade or "3", topic=req.topic,
        )
        return {"type": "game", "game_type": result.get("type", ""), **{k: v for k, v in result.items() if k != "type"}}
    else:
        ws = await content_generator.generate_worksheet(
            subject="综合", grade=req.grade or "3", topic=req.topic,
        )
        return {
            "type": "worksheet",
            "title": ws.title,
            "sections": ws.sections,
            "answer_key": ws.answer_key,
            "instructions": ws.instructions,
        }
