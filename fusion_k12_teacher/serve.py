"""FastAPI HTTP API 入口 — 暴露 5 大引擎为 REST API。"""

from __future__ import annotations

import asyncio
import json
import logging
import logging.config
import os
import secrets
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field, model_validator

from . import __version__
from .agent import list_available_tasks, register_all_engines, scheduler
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
from .standards import StandardsAligner, StandardsLoader, StandardsQuery
from .subjects import SubjectExpert

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    # P2: serve 经 uvicorn 启动, cli.py basicConfig 仅 CLI 路径生效, serve 路径无配置。
    # 统一 dictConfig: env LOG_LEVEL 调级别, 带时间/级别/模块, 免裸 getLogger 无格式。
    level = os.environ.get("LOG_LEVEL", os.environ.get("FUSION_K12_LOG_LEVEL", "INFO")).upper()
    fmt = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"default": {"format": fmt, "datefmt": "%Y-%m-%d %H:%M:%S"}},
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "stream": "ext://sys.stderr",
            }
        },
        "root": {"level": level, "handlers": ["console"]},
    })


_configure_logging()


def _mask_sid(sid: Any) -> str:
    # P2: 学生 ID 属 PII, 日志中不落原文, 统一短哈希前缀 (与 analytics._mask_sid 同策略)。
    import hashlib
    s = str(sid or "")
    return "S" + hashlib.sha1(s.encode("utf-8")).hexdigest()[:6] if s else ""


_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)
# R1: API key 改每请求读 env — 运行期轮换密钥即时生效, 不再导入时固化。模块常量留空,
# require_api_key 内 os.environ.get 现取。lifespan 启动日志仍可 log key 是否已配置。
_RATE_WINDOW = int(os.environ.get("FUSION_K12_RATE_WINDOW", "60"))
_RATE_MAX = int(os.environ.get("FUSION_K12_RATE_MAX", "60"))
# A1: 跨进程共享速率限制状态文件 — uvicorn --workers N / 多节点各进程共一份令牌桶。
# env 覆盖可指向共享挂载点; 留空回退进程内限流(仅单 worker 正确)。
_RATE_STATE_FILE = os.environ.get("FUSION_K12_RATE_STATE_FILE", "")


class _RateLimiter:
    """滑动窗口限流 (SRV-2) — 按 client IP 限速。

    A1: 优先用 fcntl 文件锁 + 共享状态文件, 多 worker/多节点共用一份配额。
    无共享文件(单 worker)时回退进程内 deque。
    """

    def __init__(self, window: int, max_req: int, state_file: str = ""):
        self._window = window
        self._max = max_req
        self._state_file = state_file
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    def _check_shared(self, key: str, now: float) -> bool:
        # A1: 文件锁保护跨进程读写 — 读整文件 → 更新该 key 的 deque → 原子写回。
        import fcntl
        os.makedirs(os.path.dirname(self._state_file), exist_ok=True)
        fd = os.open(self._state_file, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            data: dict[str, list[float]] = {}
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                raw = os.read(fd, 1 << 20).decode("utf-8")
                if raw.strip():
                    data = json.loads(raw)
            except (OSError, json.JSONDecodeError):
                data = {}
            hits = deque(data.get(key, []))
            cutoff = now - self._window
            while hits and hits[0] < cutoff:
                hits.popleft()
            if len(hits) >= self._max:
                return False
            hits.append(now)
            data[key] = list(hits)
            os.lseek(fd, 0, os.SEEK_SET)
            os.ftruncate(fd, 0)
            os.write(fd, json.dumps(data).encode("utf-8"))
            return True
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    async def check(self, key: str) -> bool:
        # M2-T12: cluster 模式有共享 Redis 后端 → 跨实例统一限流计数。
        # 固定窗口: INCR key (ttl=window), 超过 _max 拒绝。各实例共享同一计数。
        cache = _shared_cache()
        if cache is not None:
            try:
                count = await cache.incr(f"rl:{key}", ttl=self._window)
                return count <= self._max
            except Exception as e:
                logger.warning("Redis 限流失败, 降级进程内: %s", e)
        now = time.monotonic()
        if self._state_file:
            # 文件 I/O 放线程池, 不阻塞 event loop
            return await asyncio.to_thread(self._check_shared, key, now)
        async with self._lock:
            dq = self._hits[key]
            cutoff = now - self._window
            while dq and dq[0] < cutoff:
                dq.popleft()
            if len(dq) >= self._max:
                return False
            dq.append(now)
            return True


def _shared_cache():
    """cluster 模式返共享 CacheBackend 单例, standalone 返 None (用进程内限流)。"""
    if os.environ.get("FUSION_K12_MODE", "").lower() != "cluster":
        return None
    if not os.environ.get("FUSION_K12_REDIS_URL", ""):
        return None
    try:
        from .cache import get_cache
        return get_cache()
    except Exception as e:
        logger.warning("加载共享缓存失败, 限流回退进程内: %s", e)
        return None


_rate_limiter = _RateLimiter(_RATE_WINDOW, _RATE_MAX, _RATE_STATE_FILE)


async def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def require_api_key(api_key: str = Security(_API_KEY_HEADER)) -> str:
    # R1: 每请求现读 env — 密钥轮换后无需重启即生效。SRV-1 fail-closed: 未配置拒所有端点。
    configured = os.environ.get("FUSION_K12_API_KEY", "")
    if not configured:
        # R3: 误配置(无 key)用 500 与未就绪(503)/限流(429)语义分离 —
        # 原返 503 致运维监控无法区分"误配置"与"未就绪", 告警失真。
        logger.error("FUSION_K12_API_KEY 未配置, 拒绝受保护端点 (fail-closed)")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API key not configured; set FUSION_K12_API_KEY",
        )
    if not api_key or not secrets.compare_digest(api_key, configured):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing or invalid X-API-Key",
        )
    return api_key


async def require_admin_api_key(api_key: str = Security(_API_KEY_HEADER)) -> str:
    # P1-5: 敏感词库写操作(add/remove)需管理员密钥, 普通 key 不可改全局规则。
    # admin key 独立 env FUSION_K12_ADMIN_API_KEY; 未配置则禁用写接口(fail-closed)。
    configured = os.environ.get("FUSION_K12_ADMIN_API_KEY", "")
    if not configured:
        logger.error("FUSION_K12_ADMIN_API_KEY 未配置, 拒绝敏感词写操作 (fail-closed)")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="admin key not configured; set FUSION_K12_ADMIN_API_KEY",
        )
    if not api_key or not secrets.compare_digest(api_key, configured):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="admin privileges required",
        )
    return api_key


async def _require_ready() -> None:
    # SRV-4: lifespan 未完成时引擎为 None, 拦截启动期请求返 503
    if not _ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="service not ready, engines still initializing",
        )

mlx_client: MLXClient | None = None
curriculum_engine: CurriculumEngine | None = None
assessment_engine: AssessmentEngine | None = None
subject_expert: SubjectExpert | None = None
personalization_engine: PersonalizationEngine | None = None
content_generator: ContentGenerator | None = None
differentiation_engine: DifferentiationEngine | None = None
standards_query: StandardsQuery | None = None
standards_loader: StandardsLoader | None = None
# P3: 暴露课标对齐/覆盖报告路由, 之前仅 DifferentiationEngine 内部用。
standards_aligner: StandardsAligner | None = None
analytics_engine: AnalyticsEngine | None = None
content_filter: ContentFilter | None = None
sensitive_wordlist: SensitiveWordList | None = None
# SRV-4: lifespan 完成前引擎为 None, 以 _ready 标志拦截启动期请求
_ready: bool = False
# P1-8: 单实例锁 — serve 进程级互斥, 防多 worker/多实例并发跑同一套引擎+调度器。
# fcntl flock LOCK_EX|LOCK_NB: 持锁方继续启动, 未持锁方启动即拒 (cli/serve/uvicorn --workers N 统一受限)。
_INSTANCE_LOCKFILE = os.environ.get(
    "FUSION_K12_INSTANCE_LOCK",
    os.path.expanduser("~/.fusion-k12/serve.lock"),
)
_instance_lockfd: int | None = None


def _is_cluster_mode() -> bool:
    # M2-T10: cluster 模式允许多实例水平扩容, 单实例锁仅 standalone 需要。
    return os.environ.get("FUSION_K12_MODE", "standalone").lower() == "cluster"


def _acquire_instance_lock() -> bool:
    global _instance_lockfd
    if _instance_lockfd is not None:
        return True
    # M2-T10: cluster 模式多实例共存, 跳过进程级互斥 (跨实例去重靠 DB 行锁, 见 scheduler T11)。
    if _is_cluster_mode():
        logger.info("cluster 模式, 跳过单实例锁 (多实例水平扩容)")
        return True
    try:
        import fcntl
    except ImportError:
        logger.warning("fcntl 不可用, 跳过单实例锁")
        return True
    try:
        os.makedirs(os.path.dirname(_INSTANCE_LOCKFILE), exist_ok=True)
        fd = os.open(_INSTANCE_LOCKFILE, os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode())
        _instance_lockfd = fd
        logger.info("获取单实例锁 (pid=%d): %s", os.getpid(), _INSTANCE_LOCKFILE)
        return True
    except OSError:
        logger.error("单实例锁已被占用, 另一实例正在运行: %s — 拒绝启动", _INSTANCE_LOCKFILE)
        return False


def _release_instance_lock() -> None:
    global _instance_lockfd
    if _instance_lockfd is None:
        return
    try:
        import fcntl
        fcntl.flock(_instance_lockfd, fcntl.LOCK_UN)
    except (OSError, ImportError):
        pass
    try:
        os.close(_instance_lockfd)
    except OSError:
        pass
    _instance_lockfd = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global mlx_client, curriculum_engine, assessment_engine
    global subject_expert, personalization_engine, content_generator
    global differentiation_engine, standards_query, standards_loader, standards_aligner
    global analytics_engine, content_filter, sensitive_wordlist
    global _ready
    # SRV-5: 构建失败时 yield 不执行, 须 try/except 清理已分配资源
    try:
        # P1-8: 单实例锁 — 未持锁则拒绝启动, 防 uvicorn --workers N 多实例跑同套引擎/调度器。
        if not _acquire_instance_lock():
            raise RuntimeError(f"单实例锁已被占用: {_INSTANCE_LOCKFILE}")
        # A9: build_engines 内含 loader.load_all() 同步磁盘 I/O, 放线程池
        # 避免阻塞事件循环 — 大课标库首次加载数百毫秒, 否则并发请求全挂起。
        bundle = await asyncio.to_thread(build_engines)
        # A14: 注册与构造分离 — 工厂纯构造, 此处显式注册全局 registry(agent 执行器按名查引擎)
        register_all_engines(bundle=bundle)
        mlx_client = bundle.mlx
        curriculum_engine = bundle.curriculum
        assessment_engine = bundle.assessment
        subject_expert = bundle.subjects
        personalization_engine = bundle.personalization
        content_generator = bundle.content
        differentiation_engine = bundle.differentiation
        standards_query = bundle.standards_query
        standards_loader = bundle.standards_loader
        # P3: 复用 bundle 同一 StandardsQuery 构对齐器, 与 DifferentiationEngine 内部同实例。
        standards_aligner = StandardsAligner(query=bundle.standards_query)
        analytics_engine = bundle.analytics
        # P1-9: 复用 bundle 共享 ContentFilter — 敏感词/年龄规则一份, 不在 serve 内
        # 再各自构造致规则双份不同步 (engines.build_engines 已注入 7 引擎同实例)。
        content_filter = bundle.content_filter
        sensitive_wordlist = SensitiveWordList()
        scheduler.load_default_tasks()
        scheduler.load_history()
        scheduler.start()
        _init_allowed_dirs()
        _ready = True
        logger.info("Fusion-K12-Teacher API started, MLXClient initialized")
    except Exception as exc:
        logger.error("lifespan 启动失败, 清理已分配资源: %s", exc, exc_info=True)
        _ready = False
        # R2: 释放已构造的 mlx/scheduler, 并清空所有引擎全局 —
        # 原 re-raise 后半数全局已赋值、半数仍 None, worker 残留半套引擎。
        try:
            await scheduler.aclose()
        except Exception as e:
            logger.warning("scheduler.aclose 失败(启动异常清理): %s", e)
        if mlx_client is not None:
            try:
                await mlx_client.close()
            except Exception as e:
                logger.warning("mlx_client.close 失败(启动异常清理): %s", e)
        # 清空引擎全局, 防重启时残留半初始化态
        for name in (
            "mlx_client", "curriculum_engine", "assessment_engine", "subject_expert",
            "personalization_engine", "content_generator", "differentiation_engine",
            "standards_query", "standards_loader", "standards_aligner", "analytics_engine",
            "content_filter", "sensitive_wordlist",
        ):
            globals()[name] = None
        _release_instance_lock()
        raise
    yield
    logger.info("Fusion-K12-Teacher API shutting down")
    _ready = False
    try:
        await scheduler.aclose()
    except Exception as e:
        logger.warning("scheduler.aclose 失败: %s", e)
    if mlx_client is not None:
        try:
            await mlx_client.close()
        except Exception as e:
            logger.warning("mlx_client.close 失败: %s", e)
    _release_instance_lock()


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
            # SRV-6: 用标准 JSONResponse 而非 HTTPException, 确保统一错误体经正常响应链
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": f"rate limit exceeded ({_RATE_MAX}/{_RATE_WINDOW}s)"},
            )
    return await call_next(request)


def _check_engine_error(result: Any, label: str) -> None:
    # SRV-9: 引擎优雅降级返含 error 的结果时, 显式 502 而非 200+error 误导客户端
    err = getattr(result, "error", None)
    if not err and isinstance(result, dict):
        err = result.get("error")
    if err:
        logger.warning("%s 引擎失败: %s", label, err)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"{label} failed",
        )


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

    # SRV-7: 限定 progress 键数与值长, 防超大 payload
    @model_validator(mode="after")
    def _bound_progress(self):
        if len(self.progress) > 20:
            raise ValueError("progress 键数超过上限 20")
        for k, v in self.progress.items():
            if len(str(k)) > 50:
                raise ValueError("progress 键过长")
            if isinstance(v, str) and len(v) > 500:
                raise ValueError("progress 值过长")
        return self

class ContentGenerateRequest(BaseModel):
    topic: str = Field(..., max_length=100, description="主题")
    grade: str = Field("", max_length=4, description="年级")
    style: str = Field("interactive", max_length=20, description="生成风格")


# ── Health ──

@app.get("/api/health")
async def health():
    # P1-10: health 探测后端 fusion-mlx 可达性, 非静态返回。
    # /api/health = liveness (进程在) + 后端探测; /api/ready = readiness (引擎就绪)。
    backend = "unknown"
    if mlx_client is not None:
        try:
            # list_models 是 async, 直接 await (自带缓存+锁); to_thread 会漏 await 返未决协程
            models = await mlx_client.list_models()
            backend = "ok" if models is not None else "down"
        except Exception as e:
            logger.warning("health: fusion-mlx 探测失败: %s", e)
            backend = "down"
    status_code = status.HTTP_200_OK if backend != "down" else status.HTTP_503_SERVICE_UNAVAILABLE
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=status_code,
        content={"status": "ok" if backend != "down" else "degraded", "backend": backend, "version": __version__},
    )


@app.get("/api/ready")
async def ready():
    # P1-10: readiness — 引擎全就绪返 200, 否则 503。供 K8s readinessProbe / Docker HEALTHCHECK。
    if not _ready or mlx_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="service not ready",
        )
    return {"status": "ready", "version": __version__}


# ── Curriculum ──

@app.post("/api/curriculum/plan")
async def curriculum_plan(req: CurriculumPlanRequest, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    logger.info("curriculum/plan: grade=%s subject=%s topic=%s", req.grade, req.subject, req.topic)
    plan = await curriculum_engine.generate_lesson_plan(
        subject=req.subject, grade=req.grade, topic=req.topic,
    )
    _check_engine_error(plan, "curriculum/plan")
    return plan.to_dict()


# ── Assessment ──

@app.post("/api/assessment/grade")
async def assessment_grade(req: AssessmentGradeRequest, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    logger.info("assessment/grade: question=%s...", req.question[:30])
    result = await assessment_engine.grade_math(
        problem=req.question, answer=req.answer, solution=req.standard,
    )
    _check_engine_error(result, "assessment/grade")
    return {
        "score": result.score,
        "total": result.total,
        "percentage": result.percentage,
        "feedback": result.feedback,
        "improvements": result.improvements,
    }


# ── Subject ──

@app.post("/api/subject/explain")
async def subject_explain(req: SubjectExplainRequest, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    logger.info("subject/explain: subject=%s concept=%s...", req.subject, req.concept[:30])
    result = await subject_expert.explain_concept(
        subject=req.subject, grade=req.grade or "3", concept=req.concept,
    )
    _check_engine_error(result, "subject/explain")
    return result


# ── Personalize ──

@app.post("/api/personalize/path")
async def personalize_path(req: PersonalizePathRequest, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    logger.info("personalize/path: student=%s", _mask_sid(req.student_id))
    grade = req.progress.get("grade", "3")
    subject = req.progress.get("subject", "数学")
    goal = req.progress.get("goal", "综合提升")
    path = await personalization_engine.create_learning_path(
        student=req.student_id, grade=grade, subject=subject, goal=goal,
    )
    _check_engine_error(path, "personalize/path")
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
async def content_generate(req: ContentGenerateRequest, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    logger.info("content/generate: topic=%s grade=%s style=%s", req.topic, req.grade, req.style)
    if req.style == "flashcards":
        result = await content_generator.generate_flashcards(
            subject="综合", grade=req.grade or "3", topic=req.topic,
        )
        # P3: flashcards 降级返空列表 → 显式 502, 与 worksheet/game 一致, 不恒 200 空对象
        if not result:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="flashcards generation failed")
        return {"type": "flashcards", "items": result}
    elif req.style == "slides":
        result = await content_generator.generate_lesson_slides(
            subject="综合", grade=req.grade or "3", topic=req.topic,
        )
        # P3: slides 降级返空列表 → 502, 语义统一
        if not result:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="slides generation failed")
        return {"type": "slides", "items": result}
    elif req.style == "game":
        result = await content_generator.generate_educational_game(
            subject="综合", grade=req.grade or "3", topic=req.topic,
        )
        # SRV-8: 生成失败(含 error 字段)不再静默 200 空对象, 显式返 502 让客户端察觉
        if result.get("error"):
            logger.warning("content/generate game 失败: %s", result.get("error"))
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="game generation failed",
            )
        # CNT-1: 白名单字段透传, 内部 error 不外泄; LLM 的 type 不覆盖响应 type
        safe = {k: v for k, v in result.items() if k not in ("error", "type")}
        return {"type": "game", "game_type": result.get("type", ""), **safe}
    else:
        ws = await content_generator.generate_worksheet(
            subject="综合", grade=req.grade or "3", topic=req.topic,
        )
        # A13: worksheet 失败统一转 502, error 不入 200 body —
        # 原返 200 + ws.error 泄露内部错误细节, 与 _check_engine_error 转的设计自相矛盾。
        _check_engine_error(ws, "content/worksheet")
        return {
            "type": "worksheet",
            "title": ws.title,
            "sections": ws.sections,
            "answer_key": ws.answer_key,
            "instructions": ws.instructions,
        }


# ── Assessment 扩展 (P1-13: 补齐 essay/report/rubric 路由) ──

class AssessmentEssayRequest(BaseModel):
    essay: str = Field(..., max_length=5000, description="学生作文")

class AssessmentReportRequest(BaseModel):
    student: str = Field(..., max_length=50, description="学生姓名/ID")
    subject: str = Field(..., max_length=20, description="学科")
    grade: str = Field(..., max_length=4, description="年级")
    history: list[dict[str, Any]] = Field(default_factory=list, max_length=50, description="学习记录")

class AssessmentRubricRequest(BaseModel):
    assignment_type: str = Field(..., max_length=50, description="作业类型")
    grade: str = Field(..., max_length=4, description="年级")


@app.post("/api/assessment/essay")
async def assessment_essay(req: AssessmentEssayRequest, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    logger.info("assessment/essay: essay=%s...", req.essay[:30])
    result = await assessment_engine.grade_essay(essay=req.essay)
    _check_engine_error(result, "assessment/essay")
    return result.__dict__


@app.post("/api/assessment/report")
async def assessment_report(req: AssessmentReportRequest, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    logger.info("assessment/report: student=%s subject=%s", req.student, req.subject)
    result = await assessment_engine.generate_report(
        student=req.student, subject=req.subject, grade=req.grade, history=req.history,
    )
    _check_engine_error(result, "assessment/report")
    return result.__dict__


@app.post("/api/assessment/rubric")
async def assessment_rubric(req: AssessmentRubricRequest, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    logger.info("assessment/rubric: type=%s grade=%s", req.assignment_type, req.grade)
    result = await assessment_engine.generate_rubric(
        assignment_type=req.assignment_type, grade=req.grade,
    )
    if isinstance(result, dict) and result.get("error"):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="rubric failed")
    return result


# ── Subject 扩展 (P1-14: 补齐 exercise/stem_project/language_activity 路由) ──

class SubjectExerciseRequest(BaseModel):
    subject: str = Field(..., max_length=20, description="学科")
    grade: str = Field(..., max_length=4, description="年级")
    topic: str = Field(..., max_length=100, description="主题")
    difficulty: str = Field("medium", max_length=20, description="难度 easy/medium/hard")

class SubjectStemRequest(BaseModel):
    grade: str = Field(..., max_length=4, description="年级")
    topic: str = Field(..., max_length=100, description="主题")
    duration: str = Field("2课时", max_length=20, description="时长")

class SubjectLanguageRequest(BaseModel):
    grade: str = Field(..., max_length=4, description="年级")
    language: str = Field(..., max_length=20, description="语言")
    skill: str = Field(..., max_length=20, description="技能")
    theme: str = Field(..., max_length=100, description="主题")


@app.post("/api/subject/exercise")
async def subject_exercise_route(req: SubjectExerciseRequest, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    logger.info("subject/exercise: subject=%s topic=%s", req.subject, req.topic)
    result = await subject_expert.generate_exercise(
        subject=req.subject, grade=req.grade, topic=req.topic, difficulty=req.difficulty,
    )
    # P3: 降级路径现设 .error, 触发 502 而非 200 + question="生成失败"
    _check_engine_error(result, "subject/exercise")
    return result.__dict__


@app.post("/api/subject/stem-project")
async def subject_stem_project(req: SubjectStemRequest, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    logger.info("subject/stem-project: grade=%s topic=%s", req.grade, req.topic)
    result = await subject_expert.stem_project(grade=req.grade, topic=req.topic, duration=req.duration)
    if isinstance(result, dict) and result.get("error"):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="stem_project failed")
    return result


@app.post("/api/subject/language-activity")
async def subject_language_activity(req: SubjectLanguageRequest, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    logger.info("subject/language-activity: language=%s skill=%s", req.language, req.skill)
    result = await subject_expert.language_activity(
        grade=req.grade, language=req.language, skill=req.skill, theme=req.theme,
    )
    if isinstance(result, dict) and result.get("error"):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="language_activity failed")
    return result


# ── Curriculum 扩展 (P1-15: 补齐 quiz/unit_plan 路由) ──

class CurriculumQuizRequest(BaseModel):
    grade: str = Field(..., max_length=4, description="年级")
    subject: str = Field(..., max_length=20, description="学科")
    topic: str = Field(..., max_length=100, description="主题")
    num_questions: int = Field(10, ge=1, le=50, description="题目数量")

class CurriculumUnitPlanRequest(BaseModel):
    subject: str = Field(..., max_length=20, description="学科")
    grade: str = Field(..., max_length=4, description="年级")
    unit_title: str = Field(..., max_length=100, description="单元主题")
    weeks: int = Field(4, ge=1, le=20, description="周数")


@app.post("/api/curriculum/quiz")
async def curriculum_quiz(req: CurriculumQuizRequest, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    logger.info("curriculum/quiz: grade=%s subject=%s topic=%s", req.grade, req.subject, req.topic)
    quiz = await curriculum_engine.generate_quiz(
        subject=req.subject, grade=req.grade, topic=req.topic, num_questions=req.num_questions,
    )
    _check_engine_error(quiz, "curriculum/quiz")
    return quiz.to_dict()


@app.post("/api/curriculum/unit-plan")
async def curriculum_unit_plan(req: CurriculumUnitPlanRequest, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    logger.info("curriculum/unit-plan: subject=%s grade=%s unit=%s", req.subject, req.grade, req.unit_title)
    result = await curriculum_engine.generate_unit_plan(
        subject=req.subject, grade=req.grade, unit_title=req.unit_title, weeks=req.weeks,
    )
    if isinstance(result, dict) and result.get("error"):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="unit_plan failed")
    return result


# ── Personalize 扩展 (P1-16: 补齐 diagnose/recommend 路由) ──

class PersonalizeDiagnoseRequest(BaseModel):
    subject: str = Field(..., max_length=20, description="学科")
    grade: str = Field(..., max_length=4, description="年级")
    responses: list[dict[str, Any]] = Field(default_factory=list, max_length=50, description="答题记录")

class PersonalizeRecommendRequest(BaseModel):
    student: str = Field(..., max_length=50, description="学生")
    grade: str = Field(..., max_length=4, description="年级")
    subject: str = Field(..., max_length=20, description="学科")
    weakness: str = Field(..., max_length=200, description="薄弱点")


@app.post("/api/personalize/diagnose")
async def personalize_diagnose(req: PersonalizeDiagnoseRequest, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    logger.info("personalize/diagnose: subject=%s grade=%s", req.subject, req.grade)
    result = await personalization_engine.diagnose_skills(
        subject=req.subject, grade=req.grade, responses=req.responses,
    )
    if isinstance(result, dict) and result.get("error"):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="diagnose failed")
    return result


@app.post("/api/personalize/recommend")
async def personalize_recommend(req: PersonalizeRecommendRequest, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    logger.info("personalize/recommend: student=%s weakness=%s", req.student, req.weakness[:30])
    result = await personalization_engine.recommend_resources(
        student=req.student, grade=req.grade, subject=req.subject, weakness=req.weakness,
    )
    if isinstance(result, dict) and result.get("error"):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="recommend failed")
    return result


# ── Content 扩展 (parent_communication 路由) ──

class ContentParentCommRequest(BaseModel):
    student: str = Field(..., max_length=50, description="学生姓名/ID")
    grade: str = Field(..., max_length=4, description="年级")
    subject: str = Field(..., max_length=20, description="学科")
    topic: str = Field(..., max_length=100, description="主题")


@app.post("/api/content/parent-communication")
async def content_parent_communication(req: ContentParentCommRequest, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    logger.info("content/parent-communication: student=%s subject=%s", req.student, req.subject)
    result = await content_generator.generate_parent_communication(
        student=req.student, grade=req.grade, subject=req.subject, topic=req.topic,
    )
    # generate_parent_communication 失败返空串 (CNT-2: 不外泄错误), 空串表示失败 → 502
    if not result:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="parent communication failed")
    return {"content": result}


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
async def standards_list(subject: str = "", grade: str = "", _: str = Depends(require_api_key)):
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
async def standards_query_endpoint(req: StandardsQueryRequest, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
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


# P3: 暴露课标对齐/覆盖报告 — 之前仅 DifferentiationEngine 内部用, 无 CLI/serve 直达路由。
class StandardsAlignRequest(BaseModel):
    subject: str = Field(..., max_length=20, description="学科")
    grade: str = Field(..., max_length=4, description="年级")
    topic: str = Field(..., max_length=100, description="主题")


class StandardsCoverageRequest(BaseModel):
    subject: str = Field(..., max_length=20, description="学科")
    grade: str = Field(..., max_length=4, description="年级")
    objectives: list[str] = Field(..., min_length=1, max_length=50, description="教学目标")


@app.post("/api/standards/align")
async def standards_align(req: StandardsAlignRequest, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    """课标对齐 — 返回主题对应知识点/必修/拓展/前置。"""
    if standards_aligner is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="standards not ready")
    ctx = standards_aligner.align(subject=req.subject, grade=req.grade, topic=req.topic)
    return {
        "subject": req.subject,
        "grade": req.grade,
        "topic": req.topic,
        "knowledge_points": [kp.to_dict() for kp in ctx.knowledge_points],
        "must_cover": ctx.must_cover,
        "optional_advanced": ctx.optional_advanced,
        "curriculum_codes": ctx.curriculum_codes,
        "suggested_objectives": ctx.suggested_objectives,
        "prerequisite_count": len(ctx.prerequisites),
    }


@app.post("/api/standards/coverage")
async def standards_coverage(req: StandardsCoverageRequest, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    """课标覆盖报告 — 校验教学目标对知识点的覆盖度。"""
    if standards_query is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="standards not ready")
    report = standards_query.validate_coverage(
        subject=req.subject, grade=req.grade, objectives=req.objectives,
    )
    return {
        "subject": report.subject,
        "grade": report.grade,
        "total_points": report.total_points,
        "covered_points": report.covered_points,
        "coverage_ratio": report.coverage_ratio,
        "missing_points": report.missing_points,
        "details": report.details,
    }


# ── Differentiation (v0.3) ──

@app.post("/api/curriculum/plan-diff")
async def curriculum_plan_diff(req: DifferentiatedPlanRequest, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    """生成三层分层教案。"""
    logger.info("curriculum/plan-diff: subject=%s grade=%s topic=%s", req.subject, req.grade, req.topic)
    result = await differentiation_engine.generate_differentiated_lesson(
        subject=req.subject, grade=req.grade, topic=req.topic, duration=req.duration,
    )
    _check_engine_error(result, "curriculum/plan-diff")
    return result.to_dict()


@app.post("/api/curriculum/quiz-diff")
async def curriculum_quiz_diff(req: DifferentiatedQuizRequest, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    """生成三层分层测验。"""
    logger.info("curriculum/quiz-diff: subject=%s grade=%s topic=%s", req.subject, req.grade, req.topic)
    result = await differentiation_engine.generate_differentiated_quiz(
        subject=req.subject, grade=req.grade, topic=req.topic, num_questions=req.num_questions,
    )
    _check_engine_error(result, "curriculum/quiz-diff")
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

    # P2: 单记录大小无界 → 巨记录内存耗尽。限定每记录 JSON 序列化字节上限。
    _MAX_RECORD_BYTES = 64 * 1024

    @model_validator(mode="after")
    def _bound_record_size(self):
        import json as _j
        for i, rec in enumerate(self.data):
            try:
                size = len(_j.dumps(rec, ensure_ascii=False))
            except (TypeError, ValueError):
                raise ValueError(f"记录 #{i} 不可序列化")
            if size > self._MAX_RECORD_BYTES:
                raise ValueError(f"记录 #{i} 超过单记录上限 {self._MAX_RECORD_BYTES} 字节 (实际 {size})")
        return self

class ContentWorksheetDiffRequest(BaseModel):
    subject: str = Field(..., max_length=20, description="学科")
    grade: str = Field(..., max_length=4, description="年级")
    topic: str = Field(..., max_length=100, description="主题")
    num_questions: int = Field(8, ge=1, le=50, description="每层题目数量")


_ALLOWED_DATA_DIRS: list[Path] = []


def _init_allowed_dirs():
    # R7: 单一真源 — 复用 analytics.loader._allowed_data_dirs(), 不再 serve 侧重复定义。
    # 原两套允许目录来源分叉, 改一处忘改另一处致路径校验失效或过严。
    from .analytics.loader import _allowed_data_dirs
    global _ALLOWED_DATA_DIRS
    _ALLOWED_DATA_DIRS = _allowed_data_dirs()
    logger.info("allowed data dirs: %s", [str(d) for d in _ALLOWED_DATA_DIRS])


def _check_allowed_path(path: str) -> Path:
    """校验 data_path 在允许目录内 (SRV-5: is_relative_to 精确匹配，非前缀)。

    AGT-2/R7: 复用 loader.validate_data_path 白名单, CLI/tasks/serve 同源校验。
    """
    try:
        from .analytics.loader import DataPathError, validate_data_path
        return validate_data_path(path)
    except DataPathError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


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
async def analytics_class_profile(req: ClassProfileRequest, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    """生成班级学情画像。"""
    logger.info("analytics/class-profile: class=%s subject=%s grade=%s", req.class_id, req.subject, req.grade)
    assessments = await _load_assessments(req.data_path)
    profile = await analytics_engine.build_class_profile(
        class_id=req.class_id, subject=req.subject, grade=req.grade, assessments=assessments,
    )
    _check_engine_error(profile, "analytics/class-profile")
    return profile.to_dict()


@app.post("/api/analytics/student-profile")
async def analytics_student_profile(req: StudentProfileRequest, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    """生成学生个体画像。"""
    logger.info("analytics/student-profile: student=%s subject=%s grade=%s", _mask_sid(req.student_id), req.subject, req.grade)
    all_assessments = await _load_assessments(req.data_path)
    history = [a for a in all_assessments if a.student_id == req.student_id]
    profile = await analytics_engine.build_student_profile(
        student_id=req.student_id, subject=req.subject, grade=req.grade, history=history,
    )
    _check_engine_error(profile, "analytics/student-profile")
    return profile.to_dict()


@app.post("/api/analytics/error-analysis")
async def analytics_error_analysis(req: ErrorAnalysisRequest, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    """错题归因分析。"""
    logger.info("analytics/error-analysis: subject=%s grade=%s", req.subject, req.grade)
    all_assessments = await _load_assessments(req.data_path)
    responses = []
    for a in all_assessments:
        responses.extend(a.responses)
    errors = await analytics_engine.analyze_errors(
        subject=req.subject, grade=req.grade, responses=responses,
    )
    # P2: analyze_errors 降级返含 error_id=err-fallback 的兜底条目, 检查 error 透传失败状态。
    if errors and getattr(errors[0], "error_type", "") == "unknown" and errors[0].root_cause == "分析失败，需人工检查":
        logger.warning("analytics/error-analysis 降级回退")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="error-analysis failed",
        )
    return {"total": len(errors), "errors": [e.to_dict() for e in errors]}


@app.post("/api/analytics/remedial")
async def analytics_remedial(req: RemedialPlanRequest, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    """生成补救教学方案。"""
    logger.info("analytics/remedial: student=%s subject=%s grade=%s", _mask_sid(req.student_id), req.subject, req.grade)
    all_assessments = await _load_assessments(req.data_path)
    history = [a for a in all_assessments if a.student_id == req.student_id]
    student_profile = await analytics_engine.build_student_profile(
        student_id=req.student_id, subject=req.subject, grade=req.grade, history=history,
    )
    _check_engine_error(student_profile, "analytics/student-profile")
    # P2: 不再凭空 fabricate error_rate=0.5 — 从 knowledge_mastery 派生真实薄弱点。
    # 掌握度 < 60 视薄弱, error_rate = 1 - mastery/100; 无薄弱点则返空方案 (而非喂假数据)。
    weak_points = []
    for kp, mastery in student_profile.knowledge_mastery.items():
        if mastery < 60:
            weak_points.append(WeakPoint(
                knowledge_point_id="",
                knowledge_point_name=str(kp),
                error_rate=round(max(0.0, min(1.0, 1.0 - mastery / 100.0)), 2),
            ))
    weak_points = weak_points[:5]
    plan = await analytics_engine.generate_remedial_plan(
        student_id=req.student_id, subject=req.subject, grade=req.grade, weak_points=weak_points,
    )
    _check_engine_error(plan, "analytics/remedial")
    return plan.to_dict()


@app.post("/api/analytics/class-report")
async def analytics_class_report(req: ClassReportRequest, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    """生成班级学情报告(Markdown)。"""
    logger.info("analytics/class-report: class=%s subject=%s grade=%s", req.class_id, req.subject, req.grade)
    assessments = await _load_assessments(req.data_path)
    profile = await analytics_engine.build_class_profile(
        class_id=req.class_id, subject=req.subject, grade=req.grade, assessments=assessments,
    )
    _check_engine_error(profile, "analytics/class-profile")
    report = await analytics_engine.generate_class_report(profile)
    return {"class_id": req.class_id, "report": report}


@app.post("/api/analytics/upload")
async def analytics_upload(req: AnalyticsUploadRequest, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    """上传学情数据 — 持久化到允许目录并返回路径，供后续 analytics 调用使用 (SRV-6)。

    R6: 未成年人姓名强制脱敏后落盘 (PII 不明文持久化); 逐记录 schema 校验拒绝畸形注入;
    日志只记计数与文件名, 不记绝对路径。
    """
    logger.info("analytics/upload: %d records, format=%s", len(req.data), req.format)
    if req.format != "json":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="only json format supported",
        )
    # R6: 上传入口强制脱敏 — student_name 落盘前转掩码 ID, 未成年人 PII 不明文存储。
    # P2: fields_to_mask 用全默认集 (phone/email/id_number/address 同掩), 不再仅 student_name。
    # 共享 anonymizer 单例: 多次上传同一学生姓名得同一掩码, 便于学情分析关联。
    anonymizer = DataAnonymizer(DesensitizeConfig())
    assessments = []
    rejected = 0
    for idx, item in enumerate(req.data):
        # R6: 逐记录 schema 校验 — 非 dict / 缺 student_id / total_score 越界 拒绝, 不静默吞畸形。
        if not isinstance(item, dict):
            rejected += 1
            logger.warning("analytics/upload: 记录 #%d 非 dict, 拒绝", idx)
            continue
        sid = item.get("student_id", "")
        if not sid or not isinstance(sid, str):
            rejected += 1
            logger.warning("analytics/upload: 记录 #%d 缺 student_id, 拒绝", idx)
            continue
        total = item.get("total_score", 0.0)
        max_score = item.get("max_score", 100.0)
        try:
            if float(total) < 0 or float(max_score) <= 0:
                rejected += 1
                logger.warning("analytics/upload: 记录 #%d 分数越界 (total=%s max=%s), 拒绝", idx, total, max_score)
                continue
        except (TypeError, ValueError):
            rejected += 1
            logger.warning("analytics/upload: 记录 #%d 分数非数值, 拒绝", idx)
            continue
        try:
            # R6: student_name 经 anonymizer 脱敏后构造, 落盘为掩码 ID
            raw_name = str(item.get("student_name", "") or "")
            anon_name = anonymizer.anonymize_name(raw_name, seq=str(idx)) if raw_name else ""
            # P2: responses 含学生原始作答 (PII), 落盘前对 student_answer 字段脱敏, 不明文持久化。
            raw_responses = item.get("responses", []) or []
            scrubbed_responses = []
            for r in raw_responses:
                if isinstance(r, dict):
                    r = dict(r)
                    if "student_answer" in r and isinstance(r["student_answer"], str):
                        r["student_answer"] = anonymizer.mask_field(r["student_answer"], "student_answer")
                scrubbed_responses.append(r)
            a = StudentAssessment(
                student_id=sid,
                student_name=anon_name,
                assessment_id=item.get("assessment_id", ""),
                subject=item.get("subject", ""),
                grade=item.get("grade", ""),
                date=item.get("date", ""),
                total_score=total,
                max_score=max_score,
                scores=item.get("scores", {}),
                responses=scrubbed_responses,
            )
            assessments.append(a)
        except Exception as e:
            rejected += 1
            logger.warning("analytics/upload: 记录 #%d 构造失败, 拒绝: %s", idx, e)
    import json as _json
    dest_dir = _ALLOWED_DATA_DIRS[0] if _ALLOWED_DATA_DIRS else Path.cwd() / "data"
    dest_dir.mkdir(parents=True, exist_ok=True)
    import time as _time
    dest = dest_dir / f"upload_{int(_time.time())}.json"

    def _write():
        with open(dest, "w", encoding="utf-8") as f:
            _json.dump([a.to_dict() for a in assessments], f, ensure_ascii=False, indent=2)

    await asyncio.to_thread(_write)
    # R6: 日志只记计数与文件名, 不记绝对路径 (防路径信息泄露)
    logger.info("analytics/upload: persisted %d records (rejected %d) -> %s", len(assessments), rejected, dest.name)
    return {
        "accepted": len(assessments),
        "rejected": rejected,
        "total": len(req.data),
        # SRV-10: 仅回传文件名, 不泄露服务端绝对路径
        "filename": dest.name,
    }


# ── Content worksheet-diff (v1.0) ──

@app.post("/api/content/worksheet-diff")
async def content_worksheet_diff(req: ContentWorksheetDiffRequest, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    """生成三层分层工作纸。"""
    logger.info("content/worksheet-diff: subject=%s grade=%s topic=%s", req.subject, req.grade, req.topic)
    result = await differentiation_engine.generate_differentiated_worksheet(
        subject=req.subject, grade=req.grade, topic=req.topic, num_questions=req.num_questions,
    )
    _check_engine_error(result, "content/worksheet-diff")
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
async def agent_list_tasks(_: str = Depends(require_api_key)):
    """列出可用任务。"""
    tasks = list_available_tasks()
    registered = scheduler.list_tasks()
    return {
        "predefined": tasks,
        "registered": [t.to_dict() for t in registered],
    }


@app.post("/api/agent/run")
async def agent_run_task(req: AgentRunRequest, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    """立即执行任务 — 每次按请求参数即时构建，避免共享 _tasks 跨请求污染 (SRV-7)。

    data_path 每次传入并重新加载数据，避免任务构建时烘焙过期数据 (AGT-5)。
    """
    logger.info("agent/run: task_id=%s subject=%s grade=%s", req.task_id, req.subject, req.grade)
    run_kwargs = {"subject": req.subject, "grade": req.grade}
    if req.data_path:
        _check_allowed_path(req.data_path)
        run_kwargs["data_path"] = req.data_path
    result = await scheduler.run_task(req.task_id, **run_kwargs)
    _check_engine_error(result, "agent/run")
    return result.to_dict()


@app.post("/api/agent/schedule")
async def agent_schedule_task(req: AgentScheduleRequest, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    """启用/禁用任务调度。"""
    logger.info("agent/schedule: task_id=%s enable=%s", req.task_id, req.enable)
    if req.enable:
        ok = scheduler.enable_task(req.task_id)
    else:
        ok = scheduler.disable_task(req.task_id)
    return {"task_id": req.task_id, "enabled": req.enable, "success": ok}


@app.get("/api/agent/history")
async def agent_history(limit: int = 20, _: str = Depends(require_api_key)):
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
async def safety_check(req: SafetyCheckRequest, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    """检查内容安全性。"""
    logger.info("safety/check: grade=%s text=%s...", req.grade, req.text[:30])
    result = content_filter.check_text(req.text, req.grade)
    return result.to_dict()


@app.post("/api/safety/filter")
async def safety_filter(req: SafetyFilterRequest, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    """过滤敏感词。"""
    logger.info("safety/filter: text=%s...", req.text[:30])
    filtered = content_filter.filter_sensitive(req.text)
    return {"filtered_text": filtered}


@app.post("/api/safety/wordlist")
async def safety_wordlist(
    req: SafetyWordlistRequest,
    _: str = Depends(require_admin_api_key),
    _r: None = Depends(_require_ready),
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
async def safety_wordlist_list(_: str = Depends(require_api_key)):
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
    _r: None = Depends(_require_ready),
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
    _r: None = Depends(_require_ready),
):
    """导出脱敏数据。"""
    logger.info("desensitize/export: %d records, mode=%s", len(req.records), req.name_mode)
    cfg = DesensitizeConfig(name_mode=req.name_mode)
    anon = DataAnonymizer(cfg)
    # SEC-19: 单向导出后反匿名表已清理, name_count 从脱敏结果中统计唯一匿名名
    desensitized = anon.export_desensitized(req.records)
    name_fields = ("student_name", "name")
    unique_names = {
        r[f] for r in desensitized for f in name_fields if r.get(f)
    }
    return {
        "desensitized": desensitized,
        "name_count": len(unique_names),
    }
