"""FastAPI HTTP API 入口 — 暴露 5 大引擎为 REST API。"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import logging.config
import os
import secrets
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Request,
    Security,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.security import APIKeyHeader
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, BeforeValidator, Field, model_validator

from . import __version__
from .agent import list_available_tasks, register_all_engines, scheduler
from .ai_client import MLXClient
from .analytics import AnalyticsEngine, load_from_csv, load_from_json
from .analytics.models import StudentAssessment, WeakPoint
from .assessment import AssessmentEngine
from .auth import AuthError, AuthService
from .classroom import ClassroomStore, LessonScripter, Packager, SessionManager
from .content import ContentGenerator
from .course import SubjectRegistry
from .curriculum import CurriculumEngine
from .desensitize import DataAnonymizer, DesensitizeConfig
from .differentiation import DifferentiationEngine
from .digital_human import DigitalHumanManager
from .engines import build_engines
from .personalization import PersonalizationEngine
from .repository import get_repository
from .safety import ContentFilter, SensitiveWordList
from .standards import StandardsAligner, StandardsLoader, StandardsQuery
from .subjects import SubjectExpert
from .textbook import TextbookLoader

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


def _on_config_change(key: str, value: str) -> None:
    """M3-T17: 可热更新配置变更回调 — 刷新引擎持有的可变配置, 不重建引擎。"""
    try:
        if key == "FUSION_MLX_MODEL" and mlx_client is not None:
            mlx_client.model = value
            logger.info("热更新 MLX 模型 → %s", value)
        elif key == "FUSION_K12_RATE_LIMIT":
            _rate_limiter._max = int(value)
            logger.info("热更新限流上限 → %s/min", value)
        elif key == "FUSION_K12_SALT":
            try:
                # anonymizer 为模块级单例, 在文件后部定义 (line ~1278), 运行期已存在
                anonymizer.config.salt = value  # noqa: F821
                anonymizer.salt = anonymizer._salt_provider.get_salt()  # noqa: F821
                logger.info("热更新脱敏 salt (长度 %d)", len(value))
            except Exception as e:
                logger.warning("salt 热更新失败: %s", e)
        elif key == "FUSION_K12_LOG_LEVEL":
            logging.getLogger("fusion_k12_teacher").setLevel(value.upper())
            logger.info("热更新日志级别 → %s", value.upper())
    except Exception as e:
        logger.warning("配置变更应用失败 %s=%s: %s", key, value, e)


def _start_config_hot_reload() -> None:
    """M3-T17: 启动配置提供者轮询 + 注册回调。FileProvider 可热更, EnvProvider 静态 no-op。"""
    try:
        from .config import get_config
        cfg = get_config()
        cfg.on_change(_on_config_change)
        cfg.start()
    except Exception as e:
        logger.warning("配置热更新启动失败 (配置仍可用, 仅无热更): %s", e)


def _stop_config_hot_reload() -> None:
    """M3-T17: 停止配置轮询线程。"""
    try:
        from .config import get_config
        get_config().stop()
    except Exception as e:
        logger.warning("配置热更新停止失败: %s", e)


def _drain_timeout() -> float:
    return float(os.environ.get("FUSION_K12_DRAIN_TIMEOUT", "30"))


async def _drain_inflight() -> None:
    """M3-T19: 等待在途请求归零, 或超时强制进入关闭。"""
    global _draining
    _draining = True
    if _inflight <= 0:
        logger.info("排水完成: 无在途请求")
        return
    timeout = _drain_timeout()
    logger.info("排水开始: %d 在途请求, 等待最多 %ss", _inflight, timeout)
    if _inflight_zero is None:
        return
    try:
        await asyncio.wait_for(_inflight_zero.wait(), timeout=timeout)
        logger.info("排水完成: 在途请求已归零")
    except TimeoutError:
        logger.warning("排水超时 %ss, 仍有 %d 在途请求, 强制关闭", timeout, _inflight)


def _install_sigterm_handler() -> None:
    """M3-T19: SIGTERM → 触发排水下线 (uvicorn 收 SIGTERM 会调 lifespan shutdown,
    此处额外提前置 _draining 拒绝新请求, 并记日志便于运维观察)。"""
    import signal
    try:
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGTERM, _on_sigterm)
        logger.info("SIGTERM 排水处理器已注册")
    except (NotImplementedError, RuntimeError) as e:
        # 非 main loop 或平台不支持 add_signal_handler (Windows) — 降级靠 lifespan shutdown
        logger.warning("SIGTERM 处理器注册失败, 靠 lifespan shutdown 排水: %s", e)


def _on_sigterm() -> None:
    """SIGTERM 回调 — 标记排水, 拒绝新请求。实际关闭由 lifespan shutdown 完成。"""
    global _draining, _ready
    _draining = True
    _ready = False
    logger.info("收到 SIGTERM, 开始排水下线 (拒绝新请求, 等在途完成)")


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
# 学科课程平台 (PRD math-doubao 解耦): SubjectRegistry 持各学科模块, 路由学科无关。
subject_registry: SubjectRegistry | None = None
# 课堂模块 (classroom PRD E1-E6, K1 文字版): 课程包/会话/判分/报告。
lesson_scripter = None
packager = None
session_manager = None
# 数字人平台层 (K2/K3): DigitalHumanManager 持 4 插件管线, serve 生命周期单例。
digital_human_manager = None
# 教师身份 + 教材目录 + 资源库: 用户身份 (X-Auth-Token) 与教材级联选择数据。
auth_service: AuthService | None = None
textbook_loader: TextbookLoader | None = None
_materials_repo = None  # 资源库持久化 repo (复用 get_repository)
# SRV-4: lifespan 完成前引擎为 None, 以 _ready 标志拦截启动期请求
_ready: bool = False
# M3-T19: 在途请求计数 — 优雅下线时等其归零。asyncio 由事件循环驱动, 但计数用普通 int
# (单线程事件循环内自增自减无竞态)。drain 完成事件用于唤醒等待协程。
_inflight: int = 0
_inflight_zero: asyncio.Event | None = None  # lifespan 内惰性建 (需绑 loop)
_draining: bool = False
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
    global analytics_engine, content_filter, sensitive_wordlist, subject_registry
    global lesson_scripter, packager, session_manager
    global digital_human_manager
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
        subject_registry = bundle.subject_registry
        # 课堂模块 (E1-E6 K1 文字版): 共用 mlx_client, 独立 SQLite store。
        _classroom_store = ClassroomStore()
        lesson_scripter = LessonScripter(mlx_client)
        packager = Packager(_classroom_store)
        session_manager = SessionManager(_classroom_store)
        # 数字人平台层 (K2/K3): 注入 mlx/registry/session_manager/scripter, prewarm 插件。
        digital_human_manager = DigitalHumanManager(
            mlx_client, subject_registry, session_manager, lesson_scripter,
        )
        await digital_human_manager.start()
        scheduler.load_default_tasks()
        scheduler.load_history()
        scheduler.start()
        _init_allowed_dirs()
        # 教师身份 + 教材目录 + 资源库: AuthService 复用 scheduler 同款 repo, 教材加载建索引。
        global auth_service, textbook_loader, _materials_repo
        try:
            _materials_repo = get_repository()
            auth_service = AuthService(_materials_repo)
            textbook_loader = TextbookLoader()
            textbook_loader.load_all()
            logger.info(
                "教师身份+教材+资源库就绪: editions=%d",
                len(textbook_loader.list_editions()),
            )
        except Exception as e:
            logger.warning("教师身份/教材初始化失败 (生成功能仍可用, 仅无身份+资源库): %s", e)
            auth_service = None
            textbook_loader = None
            _materials_repo = None
        _ready = True
        # M3-T13/T14: 审计日志器注入 scheduler 的 repo, 启用持久化。
        try:
            from .audit import get_audit_logger
            get_audit_logger().set_repo(getattr(scheduler, "_repo", None))
        except Exception as e:
            logger.warning("审计日志器注入 repo 失败 (仅内存): %s", e)
        # M3-T17: 配置热更新 — 启动轮询, 注册回调刷新引擎持有的可变配置。
        _start_config_hot_reload()
        # M3-T19: 在途计数归零事件 (绑当前 loop) + SIGTERM 排水处理
        global _inflight_zero
        _inflight_zero = asyncio.Event()
        _install_sigterm_handler()
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
    # M3-T19: 优雅排水 — 拒绝新请求, 等在途归零或超时
    global _draining
    _draining = True
    await _drain_inflight()
    # M3-T17: 停止配置轮询线程
    _stop_config_hot_reload()
    # M3-T14: 关闭前 flush 剩余审计事件
    try:
        from .audit import get_audit_logger
        await get_audit_logger().aclose()
    except Exception as e:
        logger.warning("审计关闭 flush 失败: %s", e)
    try:
        await scheduler.aclose()
    except Exception as e:
        logger.warning("scheduler.aclose 失败: %s", e)
    if digital_human_manager is not None:
        try:
            await digital_human_manager.aclose()
        except Exception as e:
            logger.warning("digital_human_manager.aclose 失败: %s", e)
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


@app.middleware("http")
async def audit_middleware(request: Request, call_next):
    """M3-T13: 审计埋点 — 每请求生成 trace_id, 记录 route/method/status/duration。

    trace_id 透传至响应头 X-Trace-Id; 学生标识哈希从请求体 student_id 字段提取。
    排除探针/指标端点 (无需审计)。审计事件异步记入 AuditLogger (T14 持久化)。
    """
    path = request.url.path
    if not path.startswith("/api/") or path in ("/api/health", "/api/ready", "/api/metrics"):
        return await call_next(request)
    from .audit import AuditEvent, get_audit_logger, new_trace_id
    # M3-T19: 排水下线期间拒绝新业务请求 (探针除外, 上面已放行)
    if _draining:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "service draining, shutting down"},
            headers={"Connection": "close", "X-Trace-Id": new_trace_id()},
        )
    trace_id = new_trace_id()
    start = time.monotonic()
    status_code = 0
    err = ""
    # M3-T19: 在途计数 +1, 完成后 -1 并通知 drain 等待者
    global _inflight
    _inflight += 1
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Trace-Id"] = trace_id
        return response
    except Exception as e:
        err = str(e)[:200]
        status_code = 500
        raise
    finally:
        _inflight -= 1
        if _inflight == 0 and _inflight_zero is not None:
            _inflight_zero.set()
        duration_ms = (time.monotonic() - start) * 1000
        # M3-T16: 指标采集 — 请求计数 + 延迟直方图
        try:
            from .metrics import get_metrics
            get_metrics().record_request(path, status_code, duration_ms / 1000.0)
        except Exception:
            pass
        student_hash = ""
        try:
            body = await request.body()
            if body:
                import json as _json
                data = _json.loads(body)
                sid = data.get("student_id") or data.get("sid") or ""
                if sid:
                    from .audit.event import hash_pii
                    student_hash = hash_pii(sid)
        except Exception:
            pass
        event = AuditEvent(
            trace_id=trace_id,
            route=path,
            method=request.method,
            status=status_code,
            duration_ms=round(duration_ms, 2),
            student_hash=student_hash,
            client_ip=request.client.host if request.client else "",
            error=err,
        )
        try:
            await get_audit_logger().record(event)
        except Exception as e:
            logger.warning("审计记录失败 (不影响请求): %s", e)


# 生成路由 → 资源类型映射 (content/generate 动态, 由响应 type 字段决定)。
# issue #14: fire-and-forget 任务须持强引用, 否则事件循环仅持弱引用可被 GC,
# 且异常只在 GC 时打印 "Task exception was never retrieved" — 统一经 _spawn_bg_task 派生。
_bg_tasks: set[asyncio.Task] = set()


def _spawn_bg_task(coro) -> asyncio.Task:
    """派生后台任务并持强引用 — done 后自动移除, 异常落结构化日志。"""
    task = asyncio.ensure_future(coro)
    _bg_tasks.add(task)

    def _done(t: asyncio.Task) -> None:
        _bg_tasks.discard(t)
        if not t.cancelled() and t.exception() is not None:
            logger.warning("后台任务异常: %s", t.exception())

    task.add_done_callback(_done)
    return task


_GEN_ROUTE_TYPES: dict[str, str | None] = {
    "/api/curriculum/plan": "lesson_plan",
    "/api/curriculum/quiz": "quiz",
    "/api/curriculum/unit-plan": "unit_plan",
    "/api/curriculum/plan-diff": "diff_lesson",
    "/api/curriculum/quiz-diff": "diff_quiz",
    "/api/assessment/grade": "grade_math",
    "/api/assessment/essay": "grade_essay",
    "/api/assessment/report": "report",
    "/api/assessment/rubric": "rubric",
    "/api/subject/explain": "explain",
    "/api/subject/exercise": "exercise",
    "/api/subject/stem-project": "stem",
    "/api/subject/language-activity": "lang_activity",
    "/api/personalize/path": "path",
    "/api/personalize/diagnose": "diagnose",
    "/api/personalize/recommend": "recommend",
    "/api/content/generate": None,
    "/api/content/parent-communication": "parent_comm",
    "/api/content/worksheet-diff": "diff_worksheet",
    "/api/standards/align": "align",
    "/api/standards/coverage": "coverage",
    "/api/standards/remediate": "remediate",
    "/api/analytics/class-profile": "class_profile",
    "/api/analytics/student-profile": "student_profile",
    "/api/analytics/error-analysis": "error_analysis",
    "/api/analytics/remedial": "remedial",
    "/api/analytics/class-report": "class_report",
    "/api/safety/check": "safety",
    "/api/desensitize/anonymize": "desensitize",
}


def _save_material_if_teacher(
    teacher_id: str | None, *, mtype: str, req: dict, result: dict
) -> None:
    if not teacher_id or not _materials_repo:
        return
    if isinstance(result, dict) and result.get("error"):
        return
    title = (
        result.get("title") if isinstance(result, dict) else None
    ) or req.get("topic") or req.get("concept") or req.get("essay", "")[:20] or mtype
    try:
        _materials_repo.save_material({
            "id": "mat_" + uuid.uuid4().hex[:12],
            "teacher_id": teacher_id,
            "edition": req.get("edition", ""),
            "subject": req.get("subject", ""),
            "grade": str(req.get("grade", "")),
            "lesson_id": str(req.get("lesson_id", "")),
            "unit_title": req.get("unit_title", ""),
            "lesson_title": req.get("lesson_title", ""),
            "type": mtype,
            "title": str(title)[:200],
            "payload": json.dumps(result, ensure_ascii=False),
            "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        logger.info("资源已保存: teacher=%s type=%s title=%s", teacher_id, mtype, title)
    except Exception as e:
        logger.warning("资源保存失败 (不影响响应): %s", e)


@app.middleware("http")
async def auto_save_material_middleware(request: Request, call_next):
    """生成路由成功后, 若带 X-Auth-Token, 自动落盘资源到资源库。

    读请求体 (缓存后下游仍可读) + 响应体, 非 200 或非生成路由则跳过。
    """
    path = request.url.path
    if request.method != "POST" or path not in _GEN_ROUTE_TYPES:
        return await call_next(request)
    token = request.headers.get("X-Auth-Token", "")
    # 预读并缓存请求体, 供下游 handler + 本中间件复用 (Starlette 缓存 _body)。
    req_data: dict = {}
    try:
        body_bytes = await request.body()

        async def _receive():
            return {"type": "http.request", "body": body_bytes, "more_body": False}
        request._receive = _receive
        if body_bytes:
            req_data = json.loads(body_bytes)
    except Exception:
        req_data = {}
    response = await call_next(request)
    if response.status_code != 200 or not token or not auth_service or not _materials_repo:
        return response
    # BaseHTTPMiddleware 的响应是流式, 须消费 body_iterator 后重建响应才能读体。
    body_chunks: list[bytes] = []
    try:
        async for chunk in response.body_iterator:
            body_chunks.append(chunk)
    except Exception:
        return response
    resp_bytes = b"".join(body_chunks)
    # 重建响应 (保持状态码/头), 否则消费后下游拿不到体。
    from starlette.responses import Response as _Resp
    new_response = _Resp(
        content=resp_bytes,
        status_code=response.status_code,
        headers=dict(response.headers),
        media_type=response.media_type,
    )
    try:
        teacher_id = await asyncio.to_thread(auth_service.verify_token, token)
    except Exception:
        teacher_id = None
    if not teacher_id:
        return new_response
    try:
        result = json.loads(resp_bytes) if resp_bytes else {}
    except Exception:
        return new_response
    mtype = _GEN_ROUTE_TYPES[path]
    if mtype is None and path == "/api/content/generate":
        mtype = result.get("type") if isinstance(result, dict) else None
        if not mtype:
            return new_response
    _spawn_bg_task(
        asyncio.to_thread(
            _save_material_if_teacher,
            teacher_id,
            mtype=mtype,
            req=req_data,
            result=result,
        )
    )
    return new_response


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

def _coerce_str(v: Any) -> str:
    if isinstance(v, (int, float)):
        return str(int(v)) if float(v).is_integer() else str(v)
    return v

GradeField = Annotated[str, BeforeValidator(_coerce_str), Field(max_length=4)]

class CurriculumPlanRequest(BaseModel):
    grade: GradeField = Field(..., description="年级")
    subject: str = Field(..., max_length=20, description="学科")
    topic: str = Field(..., max_length=100, description="主题")

class AssessmentGradeRequest(BaseModel):
    question: str = Field(..., max_length=2000, description="题目")
    answer: str = Field(..., max_length=2000, description="学生答案")
    standard: str = Field("", max_length=2000, description="参考答案/评分标准")

class SubjectExplainRequest(BaseModel):
    subject: str = Field(..., max_length=20, description="学科")
    grade: GradeField = Field("", description="年级")
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
    grade: GradeField = Field("", description="年级")
    style: str = Field("interactive", max_length=20, description="生成风格")


# ── 教师身份 ──

class AuthRegisterRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=32)
    password: str = Field(..., min_length=6, max_length=128)
    name: str = Field("", max_length=50)
    school: str = Field("", max_length=100)
    region: str = Field("", max_length=50)
    default_edition: str = Field("renjiao", max_length=20)

class AuthLoginRequest(BaseModel):
    username: str = Field(..., max_length=32)
    password: str = Field(..., max_length=128)

_AUTH_TOKEN_HEADER = APIKeyHeader(name="X-Auth-Token", auto_error=False)


async def get_optional_teacher(
    x_auth_token: str = Security(_AUTH_TOKEN_HEADER),
) -> str | None:
    """软身份 — 有 token 验证返 teacher_id, 无则 None (仅 api_key 模式不保存)。"""
    if not x_auth_token or not auth_service:
        return None
    try:
        return await asyncio.to_thread(auth_service.verify_token, x_auth_token)
    except Exception:
        return None


async def require_teacher(
    x_auth_token: str = Security(_AUTH_TOKEN_HEADER),
) -> str:
    """硬身份 — 必须有效 token, 否则 401。供 /me, /logout, 资源库读写用。"""
    if not auth_service:
        raise HTTPException(status_code=503, detail="auth service unavailable")
    tid = await asyncio.to_thread(auth_service.verify_token, x_auth_token) if x_auth_token else None
    if not tid:
        raise HTTPException(status_code=401, detail="missing or invalid X-Auth-Token")
    return tid


@app.post("/api/auth/register")
async def auth_register(req: AuthRegisterRequest):
    if not auth_service:
        raise HTTPException(status_code=503, detail="auth service unavailable")
    try:
        teacher = await asyncio.to_thread(
            auth_service.register,
            req.username, req.password, req.name, req.school, req.region, req.default_edition,
        )
    except AuthError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"teacher": teacher.to_dict()}


@app.post("/api/auth/login")
async def auth_login(req: AuthLoginRequest):
    if not auth_service:
        raise HTTPException(status_code=503, detail="auth service unavailable")
    try:
        token, teacher = await asyncio.to_thread(auth_service.login, req.username, req.password)
    except AuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    return {"token": token, "teacher": teacher.to_dict()}


@app.get("/api/auth/me")
async def auth_me(teacher_id: str = Depends(require_teacher)):
    if not auth_service:
        raise HTTPException(status_code=503, detail="auth service unavailable")
    teacher = await asyncio.to_thread(auth_service.get_teacher, teacher_id)
    if not teacher:
        raise HTTPException(status_code=404, detail="teacher not found")
    return {"teacher": teacher.to_dict()}


@app.post("/api/auth/logout")
async def auth_logout(request: Request, teacher_id: str = Depends(require_teacher)):
    if auth_service:
        token = request.headers.get("X-Auth-Token", "")
        if token:
            await asyncio.to_thread(auth_service.logout, token)
    return {"ok": True}


# ── 教材目录 ──

@app.get("/api/textbook/editions")
async def textbook_editions(_: None = Depends(_require_ready)):
    if not textbook_loader:
        raise HTTPException(status_code=503, detail="textbook loader unavailable")
    return {"editions": textbook_loader.list_editions()}


@app.get("/api/textbook/{edition}/{subject}/grades")
async def textbook_grades(edition: str, subject: str, _: None = Depends(_require_ready)):
    if not textbook_loader:
        raise HTTPException(status_code=503, detail="textbook loader unavailable")
    return {"edition": edition, "subject": subject, "grades": textbook_loader.get_grades(edition, subject)}


@app.get("/api/textbook/{edition}/{subject}/{grade}/units")
async def textbook_units(edition: str, subject: str, grade: str, _: None = Depends(_require_ready)):
    if not textbook_loader:
        raise HTTPException(status_code=503, detail="textbook loader unavailable")
    units = textbook_loader.get_units(edition, subject, grade)
    return {
        "edition": edition, "subject": subject, "grade": grade,
        "units": [u.to_dict() for u in units],
    }


@app.get("/api/textbook/{edition}/{subject}/{grade}/lesson/{lesson_id}")
async def textbook_lesson(edition: str, subject: str, grade: str, lesson_id: str, _: None = Depends(_require_ready)):
    if not textbook_loader:
        raise HTTPException(status_code=503, detail="textbook loader unavailable")
    found = textbook_loader.get_lesson(edition, subject, grade, lesson_id)
    if not found:
        raise HTTPException(status_code=404, detail="lesson not found")
    unit, lesson = found
    return {
        "edition": edition, "subject": subject, "grade": grade,
        "unit": unit.unit, "unit_title": unit.title,
        "lesson": lesson.lesson, "lesson_title": lesson.title,
        "topic": lesson.topic, "knowledge_point_ids": lesson.knowledge_point_ids,
    }


# ── 资源库 ──

@app.get("/api/materials")
async def materials_list(
    teacher_id: str = Depends(require_teacher),
    type: str | None = None,
    subject: str | None = None,
    grade: str | None = None,
    lesson_id: str | None = None,
    edition: str | None = None,
    limit: int = 100,
):
    if not _materials_repo:
        raise HTTPException(status_code=503, detail="materials repo unavailable")
    items = _materials_repo.list_materials(
        teacher_id, type=type, subject=subject, grade=grade, lesson_id=lesson_id, edition=edition, limit=limit,
    )
    return {"items": [_material_summary(m) for m in items], "total": len(items)}


@app.get("/api/materials/{material_id}")
async def materials_get(material_id: str, teacher_id: str = Depends(require_teacher)):
    if not _materials_repo:
        raise HTTPException(status_code=503, detail="materials repo unavailable")
    m = _materials_repo.get_material(material_id)
    if not m or m.get("teacher_id") != teacher_id:
        raise HTTPException(status_code=404, detail="material not found")
    try:
        payload = json.loads(m.get("payload", "{}"))
    except Exception:
        payload = {}
    return {**_material_summary(m), "payload": payload}


@app.delete("/api/materials/{material_id}")
async def materials_delete(material_id: str, teacher_id: str = Depends(require_teacher)):
    if not _materials_repo:
        raise HTTPException(status_code=503, detail="materials repo unavailable")
    ok = _materials_repo.delete_material(material_id, teacher_id)
    if not ok:
        raise HTTPException(status_code=404, detail="material not found")
    return {"ok": True}


def _material_summary(m: dict) -> dict:
    return {
        "id": m.get("id", ""),
        "type": m.get("type", ""),
        "title": m.get("title", ""),
        "edition": m.get("edition", ""),
        "subject": m.get("subject", ""),
        "grade": m.get("grade", ""),
        "lesson_id": m.get("lesson_id", ""),
        "unit_title": m.get("unit_title", ""),
        "lesson_title": m.get("lesson_title", ""),
        "created_at": m.get("created_at", ""),
    }


# ── Health ──

@app.get("/api/health")
async def health():
    # P1-10: health 探测后端 fusion-mlx 可达性, 非静态返回。
    # /api/health = liveness (进程在) + 后端探测; /api/ready = readiness (引擎就绪)。
    backend = "unknown"
    model_id = ""
    if mlx_client is not None:
        try:
            # list_models 是 async, 直接 await (自带缓存+锁); to_thread 会漏 await 返未决协程
            models = await mlx_client.list_models()
            backend = "ok" if models is not None else "down"
            if models:
                # 取当前选定聊天模型名 (无 model 时标 auto-select 状态)
                model_id = mlx_client.model or "auto"
        except Exception as e:
            logger.warning("health: fusion-mlx 探测失败: %s", e)
            backend = "down"
    status_code = status.HTTP_200_OK if backend != "down" else status.HTTP_503_SERVICE_UNAVAILABLE
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ok" if backend != "down" else "degraded",
            "backend": backend, "version": __version__,
            "model": model_id, "ready": bool(_ready),
        },
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


@app.get("/api/audit/export")
async def audit_export(
    format: str = "json",
    since: str = "",
    limit: int = 1000,
    _: str = Depends(require_admin_api_key),
):
    # M3-T15: 审计导出 — 管理员 key, JSON/CSV。limit 上限 10000 防过大响应。
    await _require_ready()
    limit = max(1, min(limit, 10000))
    repo = getattr(scheduler, "_repo", None)
    if repo is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="audit persistence unavailable (no repository)",
        )
    try:
        rows = await asyncio.to_thread(repo.load_audit, since, limit)
    except Exception as e:
        logger.warning("审计导出读取失败: %s", e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="audit export failed",
        )
    fmt = format.lower()
    if fmt == "csv":
        import csv as _csv
        import io
        buf = io.StringIO()
        if rows:
            writer = _csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(
            buf.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=audit_events.csv"},
        )
    from fastapi.responses import JSONResponse
    return JSONResponse(content={"events": rows, "count": len(rows)})


@app.get("/api/metrics")
async def metrics_endpoint(_: str = Depends(require_admin_api_key)):
    # M3-T16: Prometheus 指标端点 — exposition format, 管理员 key。
    # 探针/审计中间件已排除本端点 (path 白名单)。
    from fastapi.responses import PlainTextResponse

    from .metrics import render_prometheus
    return PlainTextResponse(render_prometheus(), media_type="text/plain; version=0.0.4")


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
    grade: GradeField = Field(..., description="年级")
    history: list[dict[str, Any]] = Field(default_factory=list, max_length=50, description="学习记录")

class AssessmentRubricRequest(BaseModel):
    assignment_type: str = Field(..., max_length=50, description="作业类型")
    grade: GradeField = Field(..., description="年级")


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
    grade: GradeField = Field(..., description="年级")
    topic: str = Field(..., max_length=100, description="主题")
    difficulty: str = Field("medium", max_length=20, description="难度 easy/medium/hard")

class SubjectStemRequest(BaseModel):
    grade: GradeField = Field(..., description="年级")
    topic: str = Field(..., max_length=100, description="主题")
    duration: str = Field("2课时", max_length=20, description="时长")

class SubjectLanguageRequest(BaseModel):
    grade: GradeField = Field(..., description="年级")
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
    grade: GradeField = Field(..., description="年级")
    subject: str = Field(..., max_length=20, description="学科")
    topic: str = Field(..., max_length=100, description="主题")
    num_questions: int = Field(10, ge=1, le=50, description="题目数量")

class CurriculumUnitPlanRequest(BaseModel):
    subject: str = Field(..., max_length=20, description="学科")
    grade: GradeField = Field(..., description="年级")
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
    grade: GradeField = Field(..., description="年级")
    responses: list[dict[str, Any]] = Field(default_factory=list, max_length=50, description="答题记录")

class PersonalizeRecommendRequest(BaseModel):
    student: str = Field(..., max_length=50, description="学生")
    grade: GradeField = Field(..., description="年级")
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
    grade: GradeField = Field(..., description="年级")
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
    grade: GradeField = Field(..., description="年级")
    topic: str = Field(..., max_length=100, description="主题")
    duration: int = Field(45, ge=5, le=240, description="课时(分钟)")

class DifferentiatedQuizRequest(BaseModel):
    subject: str = Field(..., max_length=20, description="学科")
    grade: GradeField = Field(..., description="年级")
    topic: str = Field(..., max_length=100, description="主题")
    num_questions: int = Field(5, ge=1, le=50, description="每层题目数量")

class StandardsQueryRequest(BaseModel):
    subject: str = Field(..., max_length=20, description="学科")
    grade: GradeField = Field(..., description="年级")
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
    grade: GradeField = Field(..., description="年级")
    topic: str = Field(..., max_length=100, description="主题")


class StandardsCoverageRequest(BaseModel):
    subject: str = Field(..., max_length=20, description="学科")
    grade: GradeField = Field(..., description="年级")
    objectives: list[str] = Field(..., min_length=1, max_length=50, description="教学目标")


class StandardsRemediateRequest(BaseModel):
    subject: str = Field(..., max_length=20, description="学科")
    grade: GradeField = Field(..., description="年级")
    topic: str = Field("", max_length=100, description="课题")
    missing_points: list[str] = Field(..., min_length=1, max_length=30, description="缺失知识点ID列表")


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


@app.post("/api/standards/remediate")
async def standards_remediate(req: StandardsRemediateRequest, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    """针对缺失知识点生成补齐教学方案 — 无需学情数据, 基于课标知识点+前置依赖。"""
    logger.info("standards/remediate: subject=%s grade=%s missing=%d", req.subject, req.grade, len(req.missing_points))
    if standards_query is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="standards not ready")
    if mlx_client is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="engine not ready")
    all_kps = standards_query.get_knowledge_points(req.subject, str(req.grade))
    kp_map = {kp.id: kp for kp in all_kps}
    missing_details = []
    for pid in req.missing_points[:30]:
        kp = kp_map.get(pid)
        if not kp:
            continue
        prereqs = standards_query.get_prerequisites(pid)
        missing_details.append({
            "id": kp.id,
            "topic": kp.topic,
            "description": kp.description,
            "prerequisites": [p.topic for p in prereqs[:5]],
        })
    if not missing_details:
        return {"subject": req.subject, "grade": req.grade, "topic": req.topic, "missing_points": [], "strategies": [], "error": "缺失知识点无法解析"}
    import json as _json
    details_json = _json.dumps(missing_details, ensure_ascii=False)
    prompt = f"""针对以下缺失知识点生成补齐教学方案:

学科: {req.subject} | 年级: {req.grade} | 课题: {req.topic}
缺失知识点:
{details_json}

返回JSON:
{{
    "strategies": ["针对每个缺失知识点的具体教学策略"],
    "exercises": [{{"topic": "知识点", "type": "题型", "difficulty": "easy/medium", "count": 3}}],
    "timeline": "建议补齐时间线",
    "estimated_duration": "预计补齐时长"
}}"""
    llm_err = ""
    try:
        response = await mlx_client.chat([
            {"role": "system", "content": "你是一位经验丰富的教研员, 擅长针对课标缺失知识点设计补齐教学方案。"},
            {"role": "user", "content": prompt},
        ], temperature=0.3)
        from ._parse import parse_json
        data = parse_json(response)
        if isinstance(data, dict):
            exercises = []
            raw_ex = data.get("exercises", [])
            if isinstance(raw_ex, list):
                for ex in raw_ex[:50]:
                    if not isinstance(ex, dict):
                        continue
                    exercises.append({
                        "topic": str(ex.get("topic", ""))[:200],
                        "type": str(ex.get("type", ""))[:50],
                        "difficulty": str(ex.get("difficulty", "medium"))[:20],
                        "count": int(ex.get("count", 1)) if str(ex.get("count", "1")).isdigit() else 1,
                    })
            return {
                "subject": req.subject,
                "grade": req.grade,
                "topic": req.topic,
                "missing_points": missing_details,
                "strategies": [str(s) for s in (data.get("strategies") or []) if isinstance(s, str)][:20],
                "exercises": exercises,
                "timeline": str(data.get("timeline", ""))[:1000],
                "estimated_duration": str(data.get("estimated_duration", ""))[:200],
                "error": "",
            }
        llm_err = "LLM 返回空或无法解析"
    except Exception as e:
        logger.error("standards/remediate LLM 失败: %s", e)
        llm_err = str(e)
    return {
        "subject": req.subject,
        "grade": req.grade,
        "topic": req.topic,
        "missing_points": missing_details,
        "strategies": [],
        "exercises": [],
        "timeline": "",
        "estimated_duration": "",
        "error": llm_err,
    }

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
    grade: GradeField = Field(..., description="年级")
    data_path: str = Field("", max_length=500, description="评估数据文件路径(JSON/CSV)")

class StudentProfileRequest(BaseModel):
    student_id: str = Field(..., max_length=50, description="学生ID")
    subject: str = Field(..., max_length=20, description="学科")
    grade: GradeField = Field(..., description="年级")
    data_path: str = Field("", max_length=500, description="评估数据文件路径(JSON/CSV)")

class ErrorAnalysisRequest(BaseModel):
    subject: str = Field(..., max_length=20, description="学科")
    grade: GradeField = Field(..., description="年级")
    data_path: str = Field("", max_length=500, description="评估数据文件路径(JSON/CSV)")

class RemedialPlanRequest(BaseModel):
    student_id: str = Field(..., max_length=50, description="学生ID")
    subject: str = Field(..., max_length=20, description="学科")
    grade: GradeField = Field(..., description="年级")
    data_path: str = Field("", max_length=500, description="评估数据文件路径(JSON/CSV)")

class ClassReportRequest(BaseModel):
    class_id: str = Field(..., max_length=50, description="班级ID")
    subject: str = Field(..., max_length=20, description="学科")
    grade: GradeField = Field(..., description="年级")
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
    grade: GradeField = Field(..., description="年级")
    topic: str = Field(..., max_length=100, description="主题")
    num_questions: int = Field(8, ge=1, le=50, description="每层题目数量")


_ALLOWED_DATA_DIRS: list[Path] = []

# issue #17: 上传落盘滚动保留上限 — 超出后按 mtime 清最旧文件, 防磁盘无限增长
_UPLOAD_KEEP = int(os.environ.get("FUSION_K12_UPLOAD_KEEP", "500"))


def _sweep_upload_files(dest_dir: Path, keep: int = _UPLOAD_KEEP) -> None:
    """滚动清理 upload_*.json — 只保留最新 keep 份, 失败不影响上传主流程。"""
    try:
        files = sorted(
            dest_dir.glob("upload_*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in files[keep:]:
            old.unlink(missing_ok=True)
        if len(files) > keep:
            logger.info("upload sweep: removed %d stale uploads (keep=%d)", len(files) - keep, keep)
    except Exception as e:
        logger.warning("upload sweep 失败 (不影响上传): %s", e)


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


@app.get("/api/analytics/template/json")
async def analytics_template_json(_: str = Depends(require_api_key)):
    """学情数据 JSON 模板 — 两名学生各含 scores/responses, 可直接上传验证。"""
    logger.info("analytics/template/json: 返回 JSON 模板")
    sample = [
        {
            "student_id": "S001",
            "student_name": "张小明",
            "assessment_id": "A2026001",
            "date": "2026-09-20",
            "subject": "数学",
            "grade": "3",
            "total_score": 88,
            "max_score": 100,
            "scores": {"分数概念": 9, "分数比较": 8, "分数加减": 7},
            "responses": [
                {"question_id": "Q1", "question": "1/2 的含义?", "student_answer": "一半", "correct_answer": "把整体平均分2份取1份", "correct": True},
                {"question_id": "Q2", "question": "1/3 和 1/4 谁大?", "student_answer": "1/4", "correct_answer": "1/3", "correct": False},
            ],
        },
        {
            "student_id": "S002",
            "student_name": "李小红",
            "assessment_id": "A2026001",
            "date": "2026-09-20",
            "subject": "数学",
            "grade": "3",
            "total_score": 95,
            "max_score": 100,
            "scores": {"分数概念": 10, "分数比较": 9, "分数加减": 8},
            "responses": [
                {"question_id": "Q1", "question": "1/2 的含义?", "student_answer": "整体均分2份取1份", "correct_answer": "把整体平均分2份取1份", "correct": True},
                {"question_id": "Q2", "question": "1/3 和 1/4 谁大?", "student_answer": "1/3", "correct_answer": "1/3", "correct": True},
            ],
        },
    ]
    return sample


@app.get("/api/analytics/template/csv")
async def analytics_template_csv(_: str = Depends(require_api_key)):
    """学情数据 CSV 模板 — 每行一条答题记录, 按 student_id+assessment_id 聚合。"""
    logger.info("analytics/template/csv: 返回 CSV 模板")
    csv = (
        "student_id,student_name,assessment_id,date,subject,grade,total_score,max_score,question_id,question,student_answer,correct_answer,correct\n"
        "S001,张小明,A2026001,2026-09-20,数学,3,88,100,Q1,1/2的含义?,一半,把整体平均分2份取1份,true\n"
        "S001,张小明,A2026001,2026-09-20,数学,3,88,100,Q2,1/3和1/4谁大?,1/4,1/3,false\n"
        "S002,李小红,A2026001,2026-09-20,数学,3,95,100,Q1,1/2的含义?,整体均分2份取1份,把整体平均分2份取1份,true\n"
        "S002,李小红,A2026001,2026-09-20,数学,3,95,100,Q2,1/3和1/4谁大?,1/3,1/3,true\n"
    )
    headers = {"Content-Disposition": "attachment; filename=analytics_template.csv"}
    return PlainTextResponse(content=csv, media_type="text/csv", headers=headers)


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
    # issue #17: 上传文件滚动清理 — 只保留最新 N 份, 防长期运行磁盘无限增长
    await asyncio.to_thread(_sweep_upload_files, dest_dir)
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
    grade: GradeField = Field("3", description="年级")
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
    grade: Annotated[str, BeforeValidator(_coerce_str)] = Field("3", pattern=r"^[1-9]$|^1[0-2]$", description="目标年级 1-12")

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


# ============================================================================
# 学科课程平台 (PRD math-doubao, 平台-内容解耦)
# 路由学科无关: 取 subject 参数 → SubjectRegistry 分发到具体学科模块。
# 加学科 (physics/chemistry/...) 零改本段 — 只在 course/subjects/ 注册即可。
# ============================================================================


@app.get("/api/course/subjects")
async def course_subjects(_: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    """列出已注册学科及其能力清单。"""
    if subject_registry is None:
        raise HTTPException(503, "subject registry not ready")
    return {"subjects": subject_registry.manifests()}


@app.get("/api/course/{subject}/graph/nodes")
async def course_graph_nodes(
    subject: str,
    stage: str | None = None,
    strand: str | None = None,
    grade: str | None = None,
    node_type: str | None = None,
    _: str = Depends(require_api_key),
    _r: None = Depends(_require_ready),
):
    """学科知识图谱节点列表 (按 stage/strand/grade/node_type 过滤)。"""
    mod = _get_subject_module(subject)
    kg = mod.knowledge_graph()
    if kg is None:
        raise HTTPException(501, f"学科 {subject} 未实现知识图谱")
    nodes = kg.query(stage=stage, strand=strand, grade=grade, node_type=node_type)
    return {"subject": subject, "count": len(nodes), "nodes": [n.to_dict() for n in nodes[:200]]}


@app.get("/api/course/{subject}/graph/node/{node_id}")
async def course_graph_node(
    subject: str,
    node_id: str,
    _: str = Depends(require_api_key),
    _r: None = Depends(_require_ready),
):
    """学科知识图谱节点详情 (公式/易错点/关联题型/前置链)。"""
    mod = _get_subject_module(subject)
    kg = mod.knowledge_graph()
    if kg is None:
        raise HTTPException(501, f"学科 {subject} 未实现知识图谱")
    node = kg.get_node(node_id)
    if node is None:
        raise HTTPException(404, f"节点不存在: {node_id}")
    return {
        "node": node.to_dict(),
        "prerequisites_chain": kg.prerequisites_chain(node_id),
        "reverse_attribution": kg.reverse_attribution(node_id),
    }


class CourseLessonScriptRequest(BaseModel):
    subject: str
    topic: str
    grade: str = "5"
    knowledge_node_id: str = ""
    prerequisites: list[str] = []
    misconceptions: list[str] = []
    layer: str = "B"


@app.post("/api/course/{subject}/lesson-script")
async def course_lesson_script(
    subject: str,
    req: CourseLessonScriptRequest,
    _: str = Depends(require_api_key),
    _r: None = Depends(_require_ready),
):
    """按 5E 生成学科苏格拉底课稿 DSL (UC-M1)。"""
    mod = _get_subject_module(subject)
    tutor = mod.socratic_tutor()
    if tutor is None:
        raise HTTPException(501, f"学科 {subject} 未实现苏格拉底课稿")
    dsl = await tutor.generate_lesson_script(
        topic=req.topic, grade=req.grade, knowledge_node_id=req.knowledge_node_id,
        prerequisites=req.prerequisites or None, misconceptions=req.misconceptions or None,
        layer=req.layer,
    )
    return dsl.to_dict()


class CourseCheckpointRequest(BaseModel):
    checkpoint: dict
    student_answer: str


@app.post("/api/course/{subject}/checkpoint")
async def course_checkpoint(
    subject: str,
    req: CourseCheckpointRequest,
    _: str = Depends(require_api_key),
    _r: None = Depends(_require_ready),
):
    """checkpoint 判分 — 学科 verifier 数值权威 (UC-M2)。"""
    from .course.models import Checkpoint
    mod = _get_subject_module(subject)
    tutor = mod.socratic_tutor()
    verifier = mod.verifier()
    if tutor is None and verifier is None:
        raise HTTPException(501, f"学科 {subject} 未实现判分")
    cp = Checkpoint.from_dict(req.checkpoint)
    if tutor is not None:
        result = await tutor.judge_checkpoint(cp, req.student_answer)
    else:
        result = verifier.judge_checkpoint(cp, req.student_answer)
    return result.to_dict() if hasattr(result, "to_dict") else {
        "correct": result.correct, "method": result.method,
        "detail": result.detail, "fallback": result.fallback, "hint": result.hint,
    }


class CourseSceneCompileRequest(BaseModel):
    problem_text: str
    knowledge_node_id: str = ""


@app.post("/api/course/{subject}/scene-compile")
async def course_scene_compile(
    subject: str,
    req: CourseSceneCompileRequest,
    _: str = Depends(require_api_key),
    _r: None = Depends(_require_ready),
):
    """题目 → 参数化场景 DSL (SymPy 数值覆写, UC-M2 动画渲染)。"""
    mod = _get_subject_module(subject)
    compiler = mod.scene_compiler()
    if compiler is None:
        raise HTTPException(501, f"学科 {subject} 未实现场景编译")
    dsl = await compiler.compile(req.problem_text, req.knowledge_node_id)
    return dsl.to_dict()


class CourseErrorAttributionRequest(BaseModel):
    node_id: str
    max_depth: int = 3


@app.post("/api/course/{subject}/error-attribution")
async def course_error_attribution(
    subject: str,
    req: CourseErrorAttributionRequest,
    _: str = Depends(require_api_key),
    _r: None = Depends(_require_ready),
):
    """错题 GraphRAG 逆向归因 — 沿前置依赖回溯病灶路径 (UC-M4)。"""
    mod = _get_subject_module(subject)
    kg = mod.knowledge_graph()
    if kg is None:
        raise HTTPException(501, f"学科 {subject} 未实现知识图谱")
    chain = kg.reverse_attribution(req.node_id, max_depth=req.max_depth)
    node = kg.get_node(req.node_id)
    return {
        "subject": subject,
        "source_node": node.to_dict() if node else None,
        "attribution_path": chain,
        "path_nodes": [kg.get_node(n).to_dict() if kg.get_node(n) else {"id": n} for n in chain],
    }


@app.get("/api/course/{subject}/mastery/{student_id}")
async def course_mastery(
    subject: str,
    student_id: str,
    _: str = Depends(require_api_key),
    _r: None = Depends(_require_ready),
):
    """学生学科掌握度热力 (置信度启发式, DKT 替代, UC-M3)。"""
    if subject_registry is None:
        raise HTTPException(503, "subject registry not ready")
    return {
        "subject": subject,
        "student_id": student_id,
        "profile": subject_registry.mastery.student_profile(student_id),
        "weak_nodes": subject_registry.mastery.weak_nodes(student_id),
    }


def _get_subject_module(subject: str):
    """从 registry 取学科模块, 未注册返 404。"""
    if subject_registry is None:
        raise HTTPException(503, "subject registry not ready")
    try:
        return subject_registry.get(subject)
    except Exception:
        raise HTTPException(404, f"学科未注册: {subject}")


@app.get("/api/course/{subject}/problem-bank")
async def course_problem_bank(
    subject: str,
    template_id: str | None = None,
    difficulty_layer: str | None = None,
    knowledge_node_id: str | None = None,
    misconception_tag: str | None = None,
    kind: str | None = None,
    _: str = Depends(require_api_key),
    _r: None = Depends(_require_ready),
):
    """学科题库列表 (三元组打标: 知识点 + 认知层级 + 错因)。"""
    mod = _get_subject_module(subject)
    bank = mod.problem_bank()
    if bank is None:
        raise HTTPException(404, f"学科 {subject} 未实现题库")
    problems = bank.query(
        template_id=template_id, difficulty_layer=difficulty_layer,
        knowledge_node_id=knowledge_node_id, misconception_tag=misconception_tag, kind=kind,
    )
    return {
        "subject": subject,
        "count": len(problems),
        "problems": [p.to_dict() for p in problems],
        "manifest": bank.to_manifest(),
    }


@app.get("/api/course/{subject}/problem-bank/{problem_id}")
async def course_problem_detail(
    subject: str,
    problem_id: str,
    _: str = Depends(require_api_key),
    _r: None = Depends(_require_ready),
):
    """单题详情 (含变量/期望答案/认知点)。"""
    mod = _get_subject_module(subject)
    bank = mod.problem_bank()
    if bank is None:
        raise HTTPException(404, f"学科 {subject} 未实现题库")
    p = bank.get(problem_id)
    if p is None:
        raise HTTPException(404, f"题目不存在: {problem_id}")
    return {"subject": subject, "problem": p.to_dict()}


# ── 课堂模块 (classroom PRD E1-E6, K1 文字版) ──

class ClassroomScriptRequest(BaseModel):
    subject: str = "数学"
    grade: str = "5"
    topic: str
    lesson_plan: dict = {}


class ClassroomPackRequest(BaseModel):
    subject: str = "数学"
    grade: str = "5"
    topic: str
    lesson_plan: dict = {}
    slides: list = []
    quiz: dict = {}
    script: dict = {}
    material_flags: dict = {}


_StrAny = Annotated[str, BeforeValidator(_coerce_str)]


class ClassroomAnswerRequest(BaseModel):
    session_id: str
    question_id: str
    student_answer: _StrAny
    expected_answer: _StrAny = ""
    question_type: str = "open"  # open|numeric|multiple_choice|expression
    grade: str = "5"


class ClassroomSessionRequest(BaseModel):
    code: str
    student_id: str = "guest"


@app.post("/api/classroom/script")
async def classroom_script(
    req: ClassroomScriptRequest,
    _: str = Depends(require_api_key),
    _r: None = Depends(_require_ready),
):
    """E1 讲课脚本生成 — 逐页讲稿 + 提问点 + emotion_tag。"""
    if lesson_scripter is None:
        raise HTTPException(503, "课堂模块未就绪")
    script = await lesson_scripter.generate(
        subject=req.subject, grade=req.grade, topic=req.topic,
        lesson_plan=req.lesson_plan or None,
    )
    return script.to_dict()


@app.post("/api/classroom/pack")
async def classroom_pack(
    req: ClassroomPackRequest,
    _: str = Depends(require_api_key),
    _r: None = Depends(_require_ready),
):
    """E2 课程包打包 — 教案+课件+测验+脚本 → class_id + 6 位课堂码。"""
    if packager is None:
        raise HTTPException(503, "课堂模块未就绪")
    pkg = packager.pack(
        subject=req.subject, grade=req.grade, topic=req.topic,
        lesson_plan=req.lesson_plan, slides=req.slides,
        quiz=req.quiz, script=req.script, material_flags=req.material_flags,
    )
    return pkg.to_dict()


@app.get("/api/classroom/pack/{code_or_id}")
async def classroom_get_pack(
    code_or_id: str,
    _: str = Depends(require_api_key),
    _r: None = Depends(_require_ready),
):
    """E3 学生端拉取课程包 — 按课堂码或 class_id。"""
    if packager is None:
        raise HTTPException(503, "课堂模块未就绪")
    pkg = packager.get_by_code(code_or_id) or packager.get_by_id(code_or_id)
    if pkg is None:
        raise HTTPException(404, "课堂码无效或课程包已删除")
    return pkg.to_dict()


@app.get("/api/classroom/packs")
async def classroom_list_packs(
    _: str = Depends(require_api_key),
    _r: None = Depends(_require_ready),
):
    """教师端课程包列表。"""
    if packager is None:
        raise HTTPException(503, "课堂模块未就绪")
    pkgs = packager.list_all()
    return {"count": len(pkgs), "packs": [p.to_manifest() for p in pkgs]}


@app.post("/api/classroom/session")
async def classroom_create_session(
    req: ClassroomSessionRequest,
    _: str = Depends(require_api_key),
    _r: None = Depends(_require_ready),
):
    """E5 建课堂会话 — K1 文字版仅落库 (无 LiveKit token)。"""
    if packager is None or session_manager is None:
        raise HTTPException(503, "课堂模块未就绪")
    pkg = packager.get_by_code(req.code)
    if pkg is None:
        raise HTTPException(404, "课堂码无效或课程包已删除")
    sess = session_manager.create_session(pkg.class_id, req.code, req.student_id)
    return {"session": sess.to_dict(), "package": pkg.to_dict()}


@app.patch("/api/classroom/session/{session_id}/finish")
async def classroom_finish_session(
    session_id: str,
    abandoned: bool = False,
    _: str = Depends(require_api_key),
    _r: None = Depends(_require_ready),
):
    """E5 下课 — 提交课堂记录。"""
    if session_manager is None:
        raise HTTPException(503, "课堂模块未就绪")
    sess = session_manager.finish_session(session_id, abandoned=abandoned)
    if sess is None:
        raise HTTPException(404, "会话不存在")
    return {"session": sess.to_dict()}


@app.post("/api/classroom/answer")
async def classroom_answer(
    req: ClassroomAnswerRequest,
    _: str = Depends(require_api_key),
    _r: None = Depends(_require_ready),
):
    """E4 随堂作答判分 — 复用 AssessmentEngine / course checkpoint。"""
    if session_manager is None:
        raise HTTPException(503, "课堂模块未就绪")
    correct, feedback, detail = await _judge_classroom_answer(req)
    rec = session_manager.record_answer(
        req.session_id, req.question_id, req.student_answer,
        correct=correct, feedback=feedback, detail=detail,
    )
    return rec.to_dict()


async def _judge_classroom_answer(req: ClassroomAnswerRequest) -> tuple[bool, str, str]:
    """判分分发: numeric/multiple_choice 用本地逻辑, open/expression 委托 AssessmentEngine。"""
    qtype = req.question_type
    if qtype == "multiple_choice":
        correct = req.student_answer.strip().upper() == str(req.expected_answer).strip().upper()
        return correct, "对!" if correct else f"应为 {req.expected_answer}", "multiple_choice"
    if qtype == "numeric":
        try:
            ok = abs(float(req.student_answer) - float(req.expected_answer)) <= 0.01 * max(1, abs(float(req.expected_answer)))
            return ok, "数值正确" if ok else f"应为 {req.expected_answer}", "numeric"
        except (ValueError, TypeError):
            return False, f"非数值, 应为 {req.expected_answer}", "numeric"
    # open / expression 委托 LLM 判分
    if assessment_engine is not None:
        try:
            result = await assessment_engine.grade_math(
                problem=req.question_id, answer=req.student_answer,
                solution=req.expected_answer,
            )
            return bool(getattr(result, "correct", False)), getattr(result, "feedback", ""), "llm"
        except Exception as exc:
            logger.warning("classroom LLM 判分失败: %s, 降级字符串", exc)
    # 兜底: 字符串包含
    ok = req.expected_answer.strip() in req.student_answer if req.expected_answer else False
    return ok, "参考答案匹配" if ok else "未匹配参考答案", "string_fallback"


@app.get("/api/classroom/session/{session_id}/page/{page_index}")
async def classroom_page_view(
    session_id: str,
    page_index: int,
    _: str = Depends(require_api_key),
    _r: None = Depends(_require_ready),
):
    """记录翻页进度 (E5 pages_viewed)。"""
    if session_manager is None:
        raise HTTPException(503, "课堂模块未就绪")
    session_manager.record_page_view(session_id, page_index)
    return {"session_id": session_id, "page_index": page_index, "recorded": True}


@app.get("/api/classroom/report/{session_id}")
async def classroom_report(
    session_id: str,
    _: str = Depends(require_api_key),
    _r: None = Depends(_require_ready),
):
    """E6 课堂报告 — attendance/pages/quiz_stat/question_stat/weak_points。"""
    if session_manager is None:
        raise HTTPException(503, "课堂模块未就绪")
    report = session_manager.build_report(session_id)
    return report.to_dict()


@app.get("/api/classroom/sessions/{class_id}")
async def classroom_list_sessions(
    class_id: str,
    _: str = Depends(require_api_key),
    _r: None = Depends(_require_ready),
):
    """教师端某课程包的会话列表。"""
    if session_manager is None:
        raise HTTPException(503, "课堂模块未就绪")
    sessions = session_manager.store.list_sessions(class_id)
    return {"class_id": class_id, "count": len(sessions), "sessions": sessions}


# WebSocket: 苏格拉底课稿流式生成 (PRD §12.2, 5 事件协议)
# GBNF Logits Masker 替代: 两阶段 prompt (<thinking>/<dsl>) + 后置 Pydantic 校验
@app.websocket("/ws/socratic-dsl")
async def ws_socratic_dsl(websocket: WebSocket):
    """流式推送课稿生成: start → stream_chunk(thinking) → stage_change → dsl_complete → finish/error。"""
    await websocket.accept()
    try:
        payload = await websocket.receive_json()
        subject = str(payload.get("subject", "math"))
        topic = str(payload.get("topic", ""))
        grade = str(payload.get("grade", "5"))
        if not topic:
            await websocket.send_json({"event": "error", "data": {"message": "topic 必填"}})
            await websocket.close()
            return
        await websocket.send_json({"event": "start", "data": {"stage": "thinking"}})
        if subject_registry is None:
            await websocket.send_json({"event": "error", "data": {"message": "registry not ready"}})
            await websocket.close()
            return
        try:
            mod = subject_registry.get(subject)
        except Exception as exc:
            await websocket.send_json({"event": "error", "data": {"message": str(exc)}})
            await websocket.close()
            return
        tutor = mod.socratic_tutor()
        if tutor is None:
            await websocket.send_json({"event": "error", "data": {"message": f"学科 {subject} 未实现课稿"}})
            await websocket.close()
            return
        # thinking 阶段占位 (真两阶段推理待上游 GBNF; 此处先推思考提示)
        await websocket.send_json({"event": "stream_chunk", "data": {"stage": "thinking", "text": "正在分析知识点与教学路径..."}})
        await websocket.send_json({"event": "stage_change", "data": {"new_stage": "dsl"}})
        dsl = await tutor.generate_lesson_script(
            topic=topic, grade=grade,
            knowledge_node_id=str(payload.get("knowledge_node_id", "")) or None,
            prerequisites=payload.get("prerequisites") or None,
            misconceptions=payload.get("misconceptions") or None,
            layer=str(payload.get("layer", "B")) or "B",
        )
        await websocket.send_json({"event": "dsl_complete", "data": {"dsl": dsl.to_dict(), "thinking": ""}})
        await websocket.send_json({"event": "finish", "data": {}})
    except Exception as exc:
        logger.warning("ws_socratic_dsl 异常: %s", exc)
        try:
            await websocket.send_json({"event": "error", "data": {"message": str(exc)}})
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# ==================== 数字人平台层 (K2/K3) ====================


@app.post("/api/digital-human/session")
async def dh_create_session(req: dict, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    """创建数字人会话 — 加载讲稿, prewarm 插件, 返回 session_id + 页面清单。"""
    if digital_human_manager is None:
        raise HTTPException(503, "digital_human_manager 未初始化")
    subject = str(req.get("subject", "math"))
    topic = str(req.get("topic", ""))
    grade = str(req.get("grade", "3"))
    code = str(req.get("code", ""))
    student_id = str(req.get("student_id", ""))
    layer = str(req.get("layer", "B"))
    lesson_plan = req.get("lesson_plan") or None
    # 复用已有 script — 若 req 带 script (pages), 注入 lesson_plan 避 DH 重生成讲稿
    script_pages = req.get("script", {}).get("pages") if isinstance(req.get("script"), dict) else None
    if script_pages and lesson_plan is None:
        lesson_plan = {}
    if script_pages:
        lesson_plan["script_pages"] = script_pages
    if not topic:
        raise HTTPException(400, "topic 必填")
    try:
        sess = await digital_human_manager.create_session(
            subject, topic, grade, code=code, student_id=student_id, layer=layer, lesson_plan=lesson_plan,
        )
    except Exception as exc:
        logger.error("dh_create_session 失败: %s", exc, exc_info=True)
        raise HTTPException(500, str(exc))
    return {
        "session_id": sess.session_id, "page_count": sess.page_count,
        "pages": sess.page_manifest(), "subject": sess.subject, "topic": sess.topic,
        "tts_available": sess.tts.available if sess.tts else False,
        "avatar_available": sess.avatar.available,
        "llm_available": sess.llm.available if sess.llm else False,
    }


@app.post("/api/digital-human/token")
async def dh_token(req: dict, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    """签 LiveKit token + room 名。livekit 不可用时返 WS-only 标志。"""
    if digital_human_manager is None:
        raise HTTPException(503, "digital_human_manager 未初始化")
    session_id = str(req.get("session_id", ""))
    sess = digital_human_manager.get(session_id)
    if sess is None:
        raise HTTPException(404, "会话不存在")
    room = f"class_{sess.code or sess.session_id}"
    identity = f"student_{sess.student_id or session_id[-6:]}"
    token = ""
    lk_available = False
    try:
        token = sess.livekit.sign_token(identity, room)
        lk_available = True
    except Exception as exc:
        logger.info("dh_token: LiveKit 不可用, WS 降级: %s", exc)
    return {
        "session_id": session_id, "room": room, "identity": identity,
        "token": token, "livekit_available": lk_available,
        "livekit_url": sess.livekit.url,
    }


@app.post("/api/digital-human/narrate")
async def dh_narrate(req: dict, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    """讲解指定页 — TTS 合成 + Avatar 渲染, 返回音频/帧元数据 (Phase B: WS 传音频)。"""
    if digital_human_manager is None:
        raise HTTPException(503, "digital_human_manager 未初始化")
    session_id = str(req.get("session_id", ""))
    idx = int(req.get("idx", 0))
    sess = digital_human_manager.get(session_id)
    if sess is None:
        raise HTTPException(404, "会话不存在")
    try:
        res = await sess.narrate_page(idx)
    except Exception as exc:
        logger.error("dh_narrate 失败: %s", exc, exc_info=True)
        raise HTTPException(500, str(exc))
    return res


@app.post("/api/digital-human/raise-hand")
async def dh_raise_hand(req: dict, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    """举手提问 — LLM 流式应答 (学生文字输入, Phase D 加语音)。"""
    if digital_human_manager is None:
        raise HTTPException(503, "digital_human_manager 未初始化")
    session_id = str(req.get("session_id", ""))
    text = str(req.get("text", ""))
    sess = digital_human_manager.get(session_id)
    if sess is None:
        raise HTTPException(404, "会话不存在")
    if not text:
        raise HTTPException(400, "text 必填")
    try:
        res = await sess.raise_hand(text)
    except Exception as exc:
        logger.error("dh_raise_hand 失败: %s", exc, exc_info=True)
        raise HTTPException(500, str(exc))
    return res


@app.post("/api/digital-human/finish")
async def dh_finish(req: dict, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    """结束数字人会话 — 释放资源, 落库课堂记录。"""
    if digital_human_manager is None:
        raise HTTPException(503, "digital_human_manager 未初始化")
    session_id = str(req.get("session_id", ""))
    try:
        res = await digital_human_manager.finish(session_id)
    except Exception as exc:
        logger.error("dh_finish 失败: %s", exc, exc_info=True)
        raise HTTPException(500, str(exc))
    if res is None:
        raise HTTPException(404, "会话不存在")
    return res


@app.websocket("/ws/digital-human/{session_id}")
async def ws_digital_human(websocket: WebSocket, session_id: str):
    """数字人 WS — 推送状态事件/情绪/音频, 收学生动作 (narrate/raise_hand/finish)。

    Phase B: TTS 音频走 WS 二进制帧。Phase C: 视频走 LiveKit。
    """
    await websocket.accept()
    if digital_human_manager is None:
        await websocket.send_json({"event": "error", "data": {"message": "manager 未初始化"}})
        await websocket.close()
        return
    sess = digital_human_manager.get(session_id)
    if sess is None:
        await websocket.send_json({"event": "error", "data": {"message": "会话不存在"}})
        await websocket.close()
        return
    logger.info("ws_digital_human[%s]: 连接", session_id)
    try:
        await websocket.send_json({"event": "ready", "data": {
            "page_count": sess.page_count, "pages": sess.page_manifest(),
            "tts_available": sess.tts.available if sess.tts else False,
            "asr_available": sess.asr.available if sess.asr else False,
            "avatar_available": sess.avatar.available if sess.avatar else False,
        }})
        while True:
            msg = await websocket.receive()
            if "text" in msg:
                import json as _json
                data = _json.loads(msg["text"])
                action = str(data.get("action", ""))
                if action == "narrate_page":
                    idx = int(data.get("idx", 0))
                    await websocket.send_json({"event": "narrate_start", "data": {"idx": idx}})
                    res = await sess.narrate_page(idx)
                    await websocket.send_json({"event": "narrate_done", "data": res})
                    if res.get("has_audio") and sess._last_audio:
                        await websocket.send_bytes(sess._last_audio)
                elif action == "raise_hand":
                    text = str(data.get("text", ""))
                    res = await sess.raise_hand(text)
                    await websocket.send_json({"event": "qa_done", "data": res})
                    if res.get("has_audio") and sess._last_audio:
                        await websocket.send_bytes(sess._last_audio)
                elif action == "student_speech":
                    await websocket.send_json({"event": "asr_ack", "data": {}})
                elif action == "finish":
                    await digital_human_manager.finish(session_id)
                    await websocket.send_json({"event": "finished", "data": {"session_id": session_id}})
                    break
                else:
                    await websocket.send_json({"event": "error", "data": {"message": f"未知 action: {action}"}})
            elif "bytes" in msg:
                pcm = msg["bytes"]
                await websocket.send_json({"event": "asr_start", "data": {}})
                res = await sess.on_student_speech(pcm)
                await websocket.send_json({"event": "qa_done", "data": res})
                if res.get("has_audio") and sess._last_audio:
                    await websocket.send_bytes(sess._last_audio)
    except WebSocketDisconnect:
        logger.info("ws_digital_human[%s]: 断开", session_id)
    except Exception as exc:
        logger.warning("ws_digital_human[%s] 异常: %s", session_id, exc)
        try:
            await websocket.send_json({"event": "error", "data": {"message": str(exc)}})
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# 教师 Web GUI 静态挂载 (PRD GUI §2: dist/ 由 serve.py StaticFiles 挂 /, API 走 /api/*)
_WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"
if _WEB_DIST.exists():
    app.mount("/", StaticFiles(directory=str(_WEB_DIST), html=True), name="web-gui")
    logger.info("web_gui: 挂载 dist/ %s", _WEB_DIST)
else:
    logger.debug("web_gui: dist/ 不存在, 跳过静态挂载 (开发模式用 vite dev)")

