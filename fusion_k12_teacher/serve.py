"""FastAPI HTTP API 入口 — 暴露 5 大引擎为 REST API。"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

from . import __version__
from .agent import list_available_tasks, scheduler
from .ai_client import MLXClient
from .analytics import AnalyticsEngine, load_from_csv, load_from_json
from .analytics.models import StudentAssessment, WeakPoint
from .assessment import AssessmentEngine
from .content import ContentGenerator
from .curriculum import CurriculumEngine
from .desensitize import DataAnonymizer, DesensitizeConfig
from .differentiation import DifferentiationEngine
from .engines import build_engines
from .personalization import PersonalizationEngine
from .safety import ContentFilter, SensitiveWordList
from .standards import StandardsLoader, StandardsQuery
from .subjects import SubjectExpert

logger = logging.getLogger(__name__)

_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)
_API_KEY = os.environ.get("FUSION_K12_API_KEY", "")
_RATE_WINDOW = int(os.environ.get("FUSION_K12_RATE_WINDOW", "60"))
_RATE_MAX = int(os.environ.get("FUSION_K12_RATE_MAX", "60"))


class _RateLimiter:
    """进程内滑动窗口限流 (SRV-2) — 按 client IP 限速。"""

    def __init__(self, window: int, max_req: int):
        self._window = window
        self._max = max_req
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def check(self, key: str) -> bool:
        now = time.monotonic()
        async with self._lock:
            dq = self._hits[key]
            cutoff = now - self._window
            while dq and dq[0] < cutoff:
                dq.popleft()
            if len(dq) >= self._max:
                return False
            dq.append(now)
            return True


_rate_limiter = _RateLimiter(_RATE_WINDOW, _RATE_MAX)


async def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def require_api_key(api_key: str = Security(_API_KEY_HEADER)) -> str:
    if not _API_KEY:
        return ""
    if not api_key or api_key != _API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing or invalid X-API-Key",
        )
    return api_key

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
    bundle = build_engines()
    mlx_client = bundle.mlx
    curriculum_engine = bundle.curriculum
    assessment_engine = bundle.assessment
    subject_expert = bundle.subjects
    personalization_engine = bundle.personalization
    content_generator = bundle.content
    differentiation_engine = bundle.differentiation
    standards_query = bundle.standards_query
    standards_loader = bundle.standards_loader
    analytics_engine = bundle.analytics
    content_filter = ContentFilter()
    sensitive_wordlist = SensitiveWordList()
    scheduler.load_default_tasks()
    scheduler.load_history()
    scheduler.start()
    _init_allowed_dirs()
    logger.info("Fusion-K12-Teacher API started, MLXClient initialized")
    yield
    logger.info("Fusion-K12-Teacher API shutting down")
    try:
        scheduler.stop()
    except Exception as e:
        logger.warning("scheduler.stop 失败: %s", e)
    if mlx_client is not None:
        try:
            await mlx_client.close()
        except Exception as e:
            logger.warning("mlx_client.close 失败: %s", e)


app = FastAPI(
    title="Fusion-K12-Teacher API",
    version=__version__,
    lifespan=lifespan,
)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """SRV-2: 滑动窗口限流，防止单个客户端拖垮本地推理资源。"""
    if request.url.path.startswith("/api/"):
        key = await _client_key(request)
        if not await _rate_limiter.check(key):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"rate limit exceeded ({_RATE_MAX}/{_RATE_WINDOW}s)",
            )
    return await call_next(request)


# ── Request/Response Models ──

class CurriculumPlanRequest(BaseModel):
    grade: str = Field(..., max_length=4, description="年级")
    subject: str = Field(..., max_length=20, description="学科")
    topic: str = Field(..., max_length=100, description="主题")

class AssessmentGradeRequest(BaseModel):
    question: str = Field(..., max_length=2000, description="题目")
    answer: str = Field(..., max_length=2000, description="学生答案")
    standard: str = Field("", max_length=2000, description="参考答案/评分标准")

class SubjectExplainRequest(BaseModel):
    subject: str = Field(..., max_length=20, description="学科")
    grade: str = Field("", max_length=4, description="年级")
    concept: str = Field(..., max_length=500, description="概念/问题")

class PersonalizePathRequest(BaseModel):
    student_id: str = Field(..., max_length=50, description="学生ID")
    progress: dict[str, Any] = Field(default_factory=dict, description="学习进度")

class ContentGenerateRequest(BaseModel):
    topic: str = Field(..., max_length=100, description="主题")
    grade: str = Field("", max_length=4, description="年级")
    style: str = Field("interactive", max_length=20, description="生成风格")


# ── Health ──

@app.get("/api/health")
async def health():
    return {"status": "ok", "version": __version__}


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
    logger.info("subject/explain: subject=%s concept=%s...", req.subject, req.concept[:30])
    result = await subject_expert.explain_concept(
        subject=req.subject, grade=req.grade or "3", concept=req.concept,
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
        # CNT-1: 白名单字段透传, 内部 error 不外泄; LLM 的 type 不覆盖响应 type
        safe = {k: v for k, v in result.items() if k not in ("error", "type")}
        return {"type": "game", "game_type": result.get("type", ""), **safe}
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
            "error": ws.error,
        }


# ── Request Models (v0.3) ──

class DifferentiatedPlanRequest(BaseModel):
    subject: str = Field(..., max_length=20, description="学科")
    grade: str = Field(..., max_length=4, description="年级")
    topic: str = Field(..., max_length=100, description="主题")
    duration: int = Field(45, ge=5, le=240, description="课时(分钟)")

class DifferentiatedQuizRequest(BaseModel):
    subject: str = Field(..., max_length=20, description="学科")
    grade: str = Field(..., max_length=4, description="年级")
    topic: str = Field(..., max_length=100, description="主题")
    num_questions: int = Field(5, ge=1, le=50, description="每层题目数量")

class StandardsQueryRequest(BaseModel):
    subject: str = Field(..., max_length=20, description="学科")
    grade: str = Field(..., max_length=4, description="年级")
    topic: str = Field("", max_length=100, description="主题关键词")


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
    class_id: str = Field(..., max_length=50, description="班级ID")
    subject: str = Field(..., max_length=20, description="学科")
    grade: str = Field(..., max_length=4, description="年级")
    data_path: str = Field("", max_length=500, description="评估数据文件路径(JSON/CSV)")

class StudentProfileRequest(BaseModel):
    student_id: str = Field(..., max_length=50, description="学生ID")
    subject: str = Field(..., max_length=20, description="学科")
    grade: str = Field(..., max_length=4, description="年级")
    data_path: str = Field("", max_length=500, description="评估数据文件路径(JSON/CSV)")

class ErrorAnalysisRequest(BaseModel):
    subject: str = Field(..., max_length=20, description="学科")
    grade: str = Field(..., max_length=4, description="年级")
    data_path: str = Field("", max_length=500, description="评估数据文件路径(JSON/CSV)")

class RemedialPlanRequest(BaseModel):
    student_id: str = Field(..., max_length=50, description="学生ID")
    subject: str = Field(..., max_length=20, description="学科")
    grade: str = Field(..., max_length=4, description="年级")
    data_path: str = Field("", max_length=500, description="评估数据文件路径(JSON/CSV)")

class ClassReportRequest(BaseModel):
    class_id: str = Field(..., max_length=50, description="班级ID")
    subject: str = Field(..., max_length=20, description="学科")
    grade: str = Field(..., max_length=4, description="年级")
    data_path: str = Field("", max_length=500, description="评估数据文件路径(JSON/CSV)")

class AnalyticsUploadRequest(BaseModel):
    data: list[dict[str, Any]] = Field(..., max_length=1000, description="评估数据(JSON数组)")
    format: str = Field("json", max_length=10, description="数据格式: json")

class ContentWorksheetDiffRequest(BaseModel):
    subject: str = Field(..., max_length=20, description="学科")
    grade: str = Field(..., max_length=4, description="年级")
    topic: str = Field(..., max_length=100, description="主题")
    num_questions: int = Field(8, ge=1, le=50, description="每层题目数量")


_ALLOWED_DATA_DIRS: list[Path] = []


def _init_allowed_dirs():
    global _ALLOWED_DATA_DIRS
    project_root = Path(__file__).resolve().parent.parent
    _ALLOWED_DATA_DIRS = [
        (project_root / "data").resolve(),
        (project_root / "examples").resolve(),
        (Path.cwd() / "data").resolve(),
    ]
    logger.info("allowed data dirs: %s", [str(d) for d in _ALLOWED_DATA_DIRS])


def _check_allowed_path(path: str) -> Path:
    """校验 data_path 在允许目录内 (SRV-5: is_relative_to 精确匹配，非前缀)。"""
    resolved = Path(path).resolve()
    if _ALLOWED_DATA_DIRS:
        allowed = False
        for d in _ALLOWED_DATA_DIRS:
            try:
                if resolved.is_relative_to(d):
                    allowed = True
                    break
            except (ValueError, OSError):
                continue
        if not allowed:
            logger.warning("_load_assessments: path outside allowed dirs: %s", resolved)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"data path not allowed: {resolved}",
            )
    return resolved


async def _load_assessments(path: str):
    """SRV-4: 同步文件 I/O 放线程池，避免阻塞 event loop。"""
    if not path:
        return []
    _check_allowed_path(path)
    if path.endswith(".csv"):
        return await asyncio.to_thread(load_from_csv, path)
    return await asyncio.to_thread(load_from_json, path)


# ── Analytics (v0.4) ──

@app.post("/api/analytics/class-profile")
async def analytics_class_profile(req: ClassProfileRequest):
    """生成班级学情画像。"""
    logger.info("analytics/class-profile: class=%s subject=%s grade=%s", req.class_id, req.subject, req.grade)
    assessments = await _load_assessments(req.data_path)
    profile = await analytics_engine.build_class_profile(
        class_id=req.class_id, subject=req.subject, grade=req.grade, assessments=assessments,
    )
    return profile.to_dict()


@app.post("/api/analytics/student-profile")
async def analytics_student_profile(req: StudentProfileRequest):
    """生成学生个体画像。"""
    logger.info("analytics/student-profile: student=%s subject=%s grade=%s", req.student_id, req.subject, req.grade)
    all_assessments = await _load_assessments(req.data_path)
    history = [a for a in all_assessments if a.student_id == req.student_id]
    profile = await analytics_engine.build_student_profile(
        student_id=req.student_id, subject=req.subject, grade=req.grade, history=history,
    )
    return profile.to_dict()


@app.post("/api/analytics/error-analysis")
async def analytics_error_analysis(req: ErrorAnalysisRequest):
    """错题归因分析。"""
    logger.info("analytics/error-analysis: subject=%s grade=%s", req.subject, req.grade)
    all_assessments = await _load_assessments(req.data_path)
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
    all_assessments = await _load_assessments(req.data_path)
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
    assessments = await _load_assessments(req.data_path)
    profile = await analytics_engine.build_class_profile(
        class_id=req.class_id, subject=req.subject, grade=req.grade, assessments=assessments,
    )
    report = await analytics_engine.generate_class_report(profile)
    return {"class_id": req.class_id, "report": report}


@app.post("/api/analytics/upload")
async def analytics_upload(req: AnalyticsUploadRequest):
    """上传学情数据 — 持久化到允许目录并返回路径，供后续 analytics 调用使用 (SRV-6)。

    不再"假装接受"，校验+落盘+返回可用的 data_path。
    """
    logger.info("analytics/upload: %d records, format=%s", len(req.data), req.format)
    if req.format != "json":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="only json format supported",
        )
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
    import json as _json
    dest_dir = _ALLOWED_DATA_DIRS[0] if _ALLOWED_DATA_DIRS else Path.cwd() / "data"
    dest_dir.mkdir(parents=True, exist_ok=True)
    import time as _time
    dest = dest_dir / f"upload_{int(_time.time())}.json"

    def _write():
        with open(dest, "w", encoding="utf-8") as f:
            _json.dump([a.to_dict() for a in assessments], f, ensure_ascii=False, indent=2)

    await asyncio.to_thread(_write)
    logger.info("analytics/upload: persisted %d records to %s", len(assessments), dest)
    return {
        "accepted": len(assessments),
        "total": len(req.data),
        "data_path": str(dest),
    }


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
    task_id: str = Field(..., max_length=50, description="任务ID")
    subject: str = Field("数学", max_length=20, description="学科")
    grade: str = Field("3", max_length=4, description="年级")
    data_path: str = Field("", max_length=500, description="评估数据文件路径(每次执行重新加载, 避免过期数据)")

class AgentScheduleRequest(BaseModel):
    task_id: str = Field(..., max_length=50, description="任务ID")
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
    """立即执行任务 — 每次按请求参数即时构建，避免共享 _tasks 跨请求污染 (SRV-7)。

    data_path 每次传入并重新加载数据，避免任务构建时烘焙过期数据 (AGT-5)。
    """
    logger.info("agent/run: task_id=%s subject=%s grade=%s", req.task_id, req.subject, req.grade)
    run_kwargs = {"subject": req.subject, "grade": req.grade}
    if req.data_path:
        _check_allowed_path(req.data_path)
        run_kwargs["data_path"] = req.data_path
    result = await scheduler.run_task(req.task_id, **run_kwargs)
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
    text: str = Field(..., max_length=10000, description="待检查文本")
    grade: str = Field("3", pattern=r"^[1-9]$|^1[0-2]$", description="目标年级 1-12")

class SafetyFilterRequest(BaseModel):
    text: str = Field(..., max_length=10000, description="待过滤文本")

class SafetyWordlistRequest(BaseModel):
    word: str = Field(..., max_length=100, description="敏感词")
    action: str = Field("add", max_length=10, description="add 或 remove")


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
async def safety_wordlist(
    req: SafetyWordlistRequest,
    _: str = Depends(require_api_key),
):
    """管理敏感词库。"""
    logger.info("safety/wordlist: action=%s word=%s", req.action, req.word)
    if req.action == "add":
        sensitive_wordlist.add(req.word)
        await asyncio.to_thread(sensitive_wordlist.save)
        return {"action": "add", "word": req.word, "count": sensitive_wordlist.count}
    elif req.action == "remove":
        sensitive_wordlist.remove(req.word)
        await asyncio.to_thread(sensitive_wordlist.save)
        return {"action": "remove", "word": req.word, "count": sensitive_wordlist.count}
    return {"error": "unknown action"}


@app.get("/api/safety/wordlist")
async def safety_wordlist_list():
    """列出敏感词库。"""
    return {"count": sensitive_wordlist.count, "words": sensitive_wordlist.list_words()}


# ── Request Models (v0.6 desensitize) ──

class DesensitizeAnonRequest(BaseModel):
    records: list[dict[str, Any]] = Field(..., max_length=1000, description="待脱敏记录列表")
    name_mode: str = Field("id", max_length=10, description="匿名模式: id/mask")
    id_prefix: str = Field("S", max_length=10, description="ID前缀")

class DesensitizeExportRequest(BaseModel):
    records: list[dict[str, Any]] = Field(..., max_length=1000, description="待脱敏记录列表")
    name_mode: str = Field("id", max_length=10, description="匿名模式: id/mask")


# ── Desensitize (v0.6) ──

@app.post("/api/desensitize/anonymize")
async def desensitize_anonymize(
    req: DesensitizeAnonRequest,
    _: str = Depends(require_api_key),
):
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
async def desensitize_export(
    req: DesensitizeExportRequest,
    _: str = Depends(require_api_key),
):
    """导出脱敏数据。"""
    logger.info("desensitize/export: %d records, mode=%s", len(req.records), req.name_mode)
    cfg = DesensitizeConfig(name_mode=req.name_mode)
    anon = DataAnonymizer(cfg)
    desensitized = anon.export_desensitized(req.records)
    return {
        "desensitized": desensitized,
        "name_count": len(anon.get_name_map()),
    }
