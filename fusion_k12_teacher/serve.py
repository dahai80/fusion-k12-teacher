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
from .differentiation import DifferentiationEngine
from .standards import StandardsLoader, StandardsQuery
from .analytics import AnalyticsEngine, load_from_json, load_from_csv
from .agent import scheduler, list_available_tasks, build_task, register_all_engines
from .safety import ContentFilter, SensitiveWordList
from .desensitize import DataAnonymizer, DesensitizeConfig
from .analytics.models import WeakPoint, StudentAssessment

logger = logging.getLogger(__name__)

mlx_client: MLXClient | None = None
curriculum_engine: CurriculumEngine | None = None
assessment_engine: AssessmentEngine | None = None
subject_expert: SubjectExpert | None = None
personalization_engine: PersonalizationEngine | None = None
content_generator: ContentGenerator | None = None
differentiation_engine: DifferentiationEngine | None = None
standards_query: StandardsQuery | None = None
standards_loader: StandardsLoader | None = None
analytics_engine: AnalyticsEngine | None = None
content_filter: ContentFilter | None = None
sensitive_wordlist: SensitiveWordList | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global mlx_client, curriculum_engine, assessment_engine
    global subject_expert, personalization_engine, content_generator
    global differentiation_engine, standards_query, standards_loader
    global analytics_engine, content_filter, sensitive_wordlist
    mlx_client = MLXClient()
    curriculum_engine = CurriculumEngine(mlx_client)
    assessment_engine = AssessmentEngine(mlx_client)
    subject_expert = SubjectExpert(mlx_client)
    personalization_engine = PersonalizationEngine(mlx_client)
    content_generator = ContentGenerator(mlx_client)
    standards_loader = StandardsLoader()
    standards_loader.load_all()
    standards_query = StandardsQuery(standards_loader)
    differentiation_engine = DifferentiationEngine(mlx_client, standards_query)
    analytics_engine = AnalyticsEngine(mlx_client, standards_query)
    register_all_engines(
        curriculum=curriculum_engine,
        assessment=assessment_engine,
        subjects=subject_expert,
        personalization=personalization_engine,
        content=content_generator,
        differentiation=differentiation_engine,
        analytics=analytics_engine,
        standards_query=standards_query,
    )
    content_filter = ContentFilter()
    sensitive_wordlist = SensitiveWordList()
    scheduler.load_default_tasks()
    scheduler.load_history()
    _init_allowed_dirs()
    logger.info("Fusion-K12-Teacher API started, MLXClient initialized")
    yield
    logger.info("Fusion-K12-Teacher API shutting down")


app = FastAPI(
    title="Fusion-K12-Teacher API",
    version="1.0.2",
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
    return {"status": "ok", "version": "1.0.2"}


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


# ── Request Models (v0.3) ──

class DifferentiatedPlanRequest(BaseModel):
    subject: str = Field(..., description="学科")
    grade: str = Field(..., description="年级")
    topic: str = Field(..., description="主题")
    duration: int = Field(45, description="课时(分钟)")

class DifferentiatedQuizRequest(BaseModel):
    subject: str = Field(..., description="学科")
    grade: str = Field(..., description="年级")
    topic: str = Field(..., description="主题")
    num_questions: int = Field(5, description="每层题目数量")

class StandardsQueryRequest(BaseModel):
    subject: str = Field(..., description="学科")
    grade: str = Field(..., description="年级")
    topic: str = Field("", description="主题关键词")


# ── Standards (v0.3) ──

@app.get("/api/standards/list")
async def standards_list(subject: str = "", grade: str = ""):
    """列出课标知识点。"""
    logger.info("standards/list: subject=%s grade=%s", subject, grade)
    if subject and grade:
        points = standards_query.get_knowledge_points(subject, grade)
    elif subject:
        all_points = standards_loader.all_points()
        points = [p for p in all_points.values() if p.subject == subject]
    else:
        all_points = standards_loader.all_points()
        points = list(all_points.values())
    return {
        "total": len(points),
        "knowledge_points": [p.to_dict() for p in points[:50]],
    }


@app.post("/api/standards/query")
async def standards_query_endpoint(req: StandardsQueryRequest):
    """查询课标知识点。"""
    logger.info("standards/query: subject=%s grade=%s topic=%s", req.subject, req.grade, req.topic)
    if req.topic:
        points = standards_query.find_by_topic(req.subject, req.grade, req.topic)
    else:
        points = standards_query.get_knowledge_points(req.subject, req.grade)
    return {
        "total": len(points),
        "knowledge_points": [p.to_dict() for p in points],
    }


# ── Differentiation (v0.3) ──

@app.post("/api/curriculum/plan-diff")
async def curriculum_plan_diff(req: DifferentiatedPlanRequest):
    """生成三层分层教案。"""
    logger.info("curriculum/plan-diff: subject=%s grade=%s topic=%s", req.subject, req.grade, req.topic)
    result = await differentiation_engine.generate_differentiated_lesson(
        subject=req.subject, grade=req.grade, topic=req.topic, duration=req.duration,
    )
    return result.to_dict()


@app.post("/api/curriculum/quiz-diff")
async def curriculum_quiz_diff(req: DifferentiatedQuizRequest):
    """生成三层分层测验。"""
    logger.info("curriculum/quiz-diff: subject=%s grade=%s topic=%s", req.subject, req.grade, req.topic)
    result = await differentiation_engine.generate_differentiated_quiz(
        subject=req.subject, grade=req.grade, topic=req.topic, num_questions=req.num_questions,
    )
    return result.to_dict()


# ── Request Models (v0.4) ──

class ClassProfileRequest(BaseModel):
    class_id: str = Field(..., description="班级ID")
    subject: str = Field(..., description="学科")
    grade: str = Field(..., description="年级")
    data_path: str = Field("", description="评估数据文件路径(JSON/CSV)")

class StudentProfileRequest(BaseModel):
    student_id: str = Field(..., description="学生ID")
    subject: str = Field(..., description="学科")
    grade: str = Field(..., description="年级")
    data_path: str = Field("", description="评估数据文件路径(JSON/CSV)")

class ErrorAnalysisRequest(BaseModel):
    subject: str = Field(..., description="学科")
    grade: str = Field(..., description="年级")
    data_path: str = Field("", description="评估数据文件路径(JSON/CSV)")

class RemedialPlanRequest(BaseModel):
    student_id: str = Field(..., description="学生ID")
    subject: str = Field(..., description="学科")
    grade: str = Field(..., description="年级")
    data_path: str = Field("", description="评估数据文件路径(JSON/CSV)")

class ClassReportRequest(BaseModel):
    class_id: str = Field(..., description="班级ID")
    subject: str = Field(..., description="学科")
    grade: str = Field(..., description="年级")
    data_path: str = Field("", description="评估数据文件路径(JSON/CSV)")

class AnalyticsUploadRequest(BaseModel):
    data: List[Dict[str, Any]] = Field(..., description="评估数据(JSON数组)")
    format: str = Field("json", description="数据格式: json")

class ContentWorksheetDiffRequest(BaseModel):
    subject: str = Field(..., description="学科")
    grade: str = Field(..., description="年级")
    topic: str = Field(..., description="主题")
    num_questions: int = Field(8, description="每层题目数量")


_ALLOWED_DATA_DIRS: list[str] = []


def _init_allowed_dirs():
    global _ALLOWED_DATA_DIRS
    from pathlib import Path
    project_root = Path(__file__).resolve().parent.parent
    _ALLOWED_DATA_DIRS = [
        str(project_root / "data"),
        str(project_root / "examples"),
        str(Path.cwd() / "data"),
    ]


def _load_assessments(path: str):
    if not path:
        return []
    from pathlib import Path
    resolved = Path(path).resolve()
    if _ALLOWED_DATA_DIRS:
        allowed = any(str(resolved).startswith(d) for d in _ALLOWED_DATA_DIRS)
        if not allowed:
            logger.warning("_load_assessments: path outside allowed dirs: %s", resolved)
            return []
    if path.endswith(".csv"):
        return load_from_csv(path)
    return load_from_json(path)


# ── Analytics (v0.4) ──

@app.post("/api/analytics/class-profile")
async def analytics_class_profile(req: ClassProfileRequest):
    """生成班级学情画像。"""
    logger.info("analytics/class-profile: class=%s subject=%s grade=%s", req.class_id, req.subject, req.grade)
    assessments = _load_assessments(req.data_path)
    profile = await analytics_engine.build_class_profile(
        class_id=req.class_id, subject=req.subject, grade=req.grade, assessments=assessments,
    )
    return profile.to_dict()


@app.post("/api/analytics/student-profile")
async def analytics_student_profile(req: StudentProfileRequest):
    """生成学生个体画像。"""
    logger.info("analytics/student-profile: student=%s subject=%s grade=%s", req.student_id, req.subject, req.grade)
    all_assessments = _load_assessments(req.data_path)
    history = [a for a in all_assessments if a.student_id == req.student_id]
    profile = await analytics_engine.build_student_profile(
        student_id=req.student_id, subject=req.subject, grade=req.grade, history=history,
    )
    return profile.to_dict()


@app.post("/api/analytics/error-analysis")
async def analytics_error_analysis(req: ErrorAnalysisRequest):
    """错题归因分析。"""
    logger.info("analytics/error-analysis: subject=%s grade=%s", req.subject, req.grade)
    all_assessments = _load_assessments(req.data_path)
    responses = []
    for a in all_assessments:
        responses.extend(a.responses)
    errors = await analytics_engine.analyze_errors(
        subject=req.subject, grade=req.grade, responses=responses,
    )
    return {"total": len(errors), "errors": [e.to_dict() for e in errors]}


@app.post("/api/analytics/remedial")
async def analytics_remedial(req: RemedialPlanRequest):
    """生成补救教学方案。"""
    logger.info("analytics/remedial: student=%s subject=%s grade=%s", req.student_id, req.subject, req.grade)
    all_assessments = _load_assessments(req.data_path)
    history = [a for a in all_assessments if a.student_id == req.student_id]
    student_profile = await analytics_engine.build_student_profile(
        student_id=req.student_id, subject=req.subject, grade=req.grade, history=history,
    )
    weak_points = [
        WeakPoint(knowledge_point_id=wn, knowledge_point_name=wn, error_rate=0.5)
        for wn in list(student_profile.knowledge_mastery.keys())[:5]
    ]
    plan = await analytics_engine.generate_remedial_plan(
        student_id=req.student_id, subject=req.subject, grade=req.grade, weak_points=weak_points,
    )
    return plan.to_dict()


@app.post("/api/analytics/class-report")
async def analytics_class_report(req: ClassReportRequest):
    """生成班级学情报告(Markdown)。"""
    logger.info("analytics/class-report: class=%s subject=%s grade=%s", req.class_id, req.subject, req.grade)
    assessments = _load_assessments(req.data_path)
    profile = await analytics_engine.build_class_profile(
        class_id=req.class_id, subject=req.subject, grade=req.grade, assessments=assessments,
    )
    report = await analytics_engine.generate_class_report(profile)
    return {"class_id": req.class_id, "report": report}


@app.post("/api/analytics/upload")
async def analytics_upload(req: AnalyticsUploadRequest):
    """上传学情数据。"""
    logger.info("analytics/upload: %d records, format=%s", len(req.data), req.format)
    assessments = []
    for item in req.data:
        try:
            a = StudentAssessment(
                student_id=item.get("student_id", ""),
                student_name=item.get("student_name", ""),
                assessment_id=item.get("assessment_id", ""),
                subject=item.get("subject", ""),
                grade=item.get("grade", ""),
                date=item.get("date", ""),
                total_score=item.get("total_score", 0.0),
                max_score=item.get("max_score", 100.0),
                scores=item.get("scores", {}),
                responses=item.get("responses", []),
            )
            assessments.append(a)
        except Exception as e:
            logger.warning("analytics/upload: skip bad record: %s", e)
    return {"accepted": len(assessments), "total": len(req.data)}


# ── Content worksheet-diff (v1.0) ──

@app.post("/api/content/worksheet-diff")
async def content_worksheet_diff(req: ContentWorksheetDiffRequest):
    """生成三层分层工作纸。"""
    logger.info("content/worksheet-diff: subject=%s grade=%s topic=%s", req.subject, req.grade, req.topic)
    result = await differentiation_engine.generate_differentiated_worksheet(
        subject=req.subject, grade=req.grade, topic=req.topic, num_questions=req.num_questions,
    )
    return result.to_dict()


# ── Request Models (v0.5) ──

class AgentRunRequest(BaseModel):
    task_id: str = Field(..., description="任务ID")
    subject: str = Field("数学", description="学科")
    grade: str = Field("3", description="年级")

class AgentScheduleRequest(BaseModel):
    task_id: str = Field(..., description="任务ID")
    enable: bool = Field(True, description="启用/禁用")


# ── Agent (v0.5) ──

@app.get("/api/agent/tasks")
async def agent_list_tasks():
    """列出可用任务。"""
    tasks = list_available_tasks()
    registered = scheduler.list_tasks()
    return {
        "predefined": tasks,
        "registered": [t.to_dict() for t in registered],
    }


@app.post("/api/agent/run")
async def agent_run_task(req: AgentRunRequest):
    """立即执行任务。"""
    logger.info("agent/run: task_id=%s subject=%s grade=%s", req.task_id, req.subject, req.grade)
    if not scheduler.get_task(req.task_id):
        scheduler.load_default_tasks(subject=req.subject, grade=req.grade)
    result = await scheduler.run_task(req.task_id)
    return result.to_dict()


@app.post("/api/agent/schedule")
async def agent_schedule_task(req: AgentScheduleRequest):
    """启用/禁用任务调度。"""
    logger.info("agent/schedule: task_id=%s enable=%s", req.task_id, req.enable)
    if req.enable:
        ok = scheduler.enable_task(req.task_id)
    else:
        ok = scheduler.disable_task(req.task_id)
    return {"task_id": req.task_id, "enabled": req.enable, "success": ok}


@app.get("/api/agent/history")
async def agent_history(limit: int = 20):
    """查看执行历史。"""
    history = scheduler.get_history(limit=limit)
    return {"total": len(history), "history": [r.to_dict() for r in history]}


# ── Request Models (v0.6) ──

class SafetyCheckRequest(BaseModel):
    text: str = Field(..., description="待检查文本")
    grade: str = Field("3", description="目标年级")

class SafetyFilterRequest(BaseModel):
    text: str = Field(..., description="待过滤文本")

class SafetyWordlistRequest(BaseModel):
    word: str = Field(..., description="敏感词")
    action: str = Field("add", description="add 或 remove")


# ── Safety (v0.6) ──

@app.post("/api/safety/check")
async def safety_check(req: SafetyCheckRequest):
    """检查内容安全性。"""
    logger.info("safety/check: grade=%s text=%s...", req.grade, req.text[:30])
    result = content_filter.check_text(req.text, req.grade)
    return result.to_dict()


@app.post("/api/safety/filter")
async def safety_filter(req: SafetyFilterRequest):
    """过滤敏感词。"""
    logger.info("safety/filter: text=%s...", req.text[:30])
    filtered = content_filter.filter_sensitive(req.text)
    return {"filtered_text": filtered}


@app.post("/api/safety/wordlist")
async def safety_wordlist(req: SafetyWordlistRequest):
    """管理敏感词库。"""
    logger.info("safety/wordlist: action=%s word=%s", req.action, req.word)
    if req.action == "add":
        sensitive_wordlist.add(req.word)
        sensitive_wordlist.save()
        return {"action": "add", "word": req.word, "count": sensitive_wordlist.count}
    elif req.action == "remove":
        sensitive_wordlist.remove(req.word)
        sensitive_wordlist.save()
        return {"action": "remove", "word": req.word, "count": sensitive_wordlist.count}
    return {"error": "unknown action"}


@app.get("/api/safety/wordlist")
async def safety_wordlist_list():
    """列出敏感词库。"""
    return {"count": sensitive_wordlist.count, "words": sensitive_wordlist.list_words()}


# ── Request Models (v0.6 desensitize) ──

class DesensitizeAnonRequest(BaseModel):
    records: List[Dict[str, Any]] = Field(..., description="待脱敏记录列表")
    name_mode: str = Field("id", description="匿名模式: id/mask")
    id_prefix: str = Field("S", description="ID前缀")

class DesensitizeExportRequest(BaseModel):
    records: List[Dict[str, Any]] = Field(..., description="待脱敏记录列表")
    name_mode: str = Field("id", description="匿名模式: id/mask")


# ── Desensitize (v0.6) ──

@app.post("/api/desensitize/anonymize")
async def desensitize_anonymize(req: DesensitizeAnonRequest):
    """对记录列表进行脱敏。"""
    logger.info("desensitize/anonymize: %d records, mode=%s", len(req.records), req.name_mode)
    cfg = DesensitizeConfig(name_mode=req.name_mode, id_prefix=req.id_prefix)
    anon = DataAnonymizer(cfg)
    result = anon.anonymize_records(req.records)
    desensitized = anon.export_desensitized(req.records)
    return {
        "result": result.to_dict(),
        "desensitized_records": desensitized,
    }


@app.post("/api/desensitize/export")
async def desensitize_export(req: DesensitizeExportRequest):
    """导出脱敏数据。"""
    logger.info("desensitize/export: %d records, mode=%s", len(req.records), req.name_mode)
    cfg = DesensitizeConfig(name_mode=req.name_mode)
    anon = DataAnonymizer(cfg)
    desensitized = anon.export_desensitized(req.records)
    name_map = anon.get_name_map()
    return {
        "desensitized": desensitized,
        "name_map": name_map,
    }
