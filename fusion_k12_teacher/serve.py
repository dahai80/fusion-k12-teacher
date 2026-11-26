# FastAPI HTTP API entrypoint — exposes the five engines as REST APIs.

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
from fastapi.responses import PlainTextResponse
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
from .errors import rethrow_if_fatal
from .personalization import PersonalizationEngine
from .repository import get_repository
from .safety import ContentFilter, SensitiveWordList
from .standards import StandardsAligner, StandardsLoader, StandardsQuery
from .subjects import SubjectExpert
from .textbook import TextbookLoader

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    # P2: serve runs under uvicorn, cli.py basicConfig only applies to the CLI path, serve path had no config.
    # Unified dictConfig: LOG_LEVEL env controls level, with time/level/module, avoiding bare unformatted getLogger.
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
    # P2: student ID is PII, never log raw value, unified short-hash prefix (same policy as analytics._mask_sid).
    import hashlib
    s = str(sid or "")
    return "S" + hashlib.sha1(s.encode("utf-8")).hexdigest()[:6] if s else ""


_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)
# R1: API key now read from env per request — runtime key rotation takes effect immediately, no import-time freeze. Module constant left empty,
# require_api_key reads os.environ.get on demand. Lifespan startup log still records whether the key is configured.
_RATE_WINDOW = int(os.environ.get("FUSION_K12_RATE_WINDOW", "60"))
_RATE_MAX = int(os.environ.get("FUSION_K12_RATE_MAX", "60"))
# A1: cross-process shared rate-limit state file — uvicorn --workers N / multi-node processes share one token bucket.
# Env override may point to a shared mount; empty falls back to in-process limiting (correct for single worker only).
_RATE_STATE_FILE = os.environ.get("FUSION_K12_RATE_STATE_FILE", "")


# Sliding-window rate limiter (SRV-2) — throttles by client IP.
#
#     A1: prefers fcntl file lock + shared state file so multiple workers/nodes share one quota.
#     Falls back to in-process deque when no shared file is configured (single worker).
class _RateLimiter:

    def __init__(self, window: int, max_req: int, state_file: str = ""):
        self._window = window
        self._max = max_req
        self._state_file = state_file
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    def _check_shared(self, key: str, now: float) -> bool:
        # A1: file lock guards cross-process read-modify-write — read whole file, update the key's deque, atomic write-back.
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
        # M2-T12: cluster mode has a shared Redis backend, cross-instance unified rate-limit counting.
        # Fixed window: INCR key (ttl=window), reject past _max. All instances share the same counter.
        cache = _shared_cache()
        if cache is not None:
            try:
                count = await cache.incr(f"rl:{key}", ttl=self._window)
                return count <= self._max
            except Exception as e:
                logger.warning("Redis rate limiting failed, falling back in-process: %s", e)
        now = time.monotonic()
        if self._state_file:
            # File I/O offloaded to thread pool so the event loop is not blocked
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


# Return the shared CacheBackend singleton in cluster mode, None in standalone (in-process rate limiting).
def _shared_cache():
    if os.environ.get("FUSION_K12_MODE", "").lower() != "cluster":
        return None
    if not os.environ.get("FUSION_K12_REDIS_URL", ""):
        return None
    try:
        from .cache import get_cache
        return get_cache()
    except Exception as e:
        logger.warning("Failed to load shared cache, rate limiting falls back in-process: %s", e)
        return None


_rate_limiter = _RateLimiter(_RATE_WINDOW, _RATE_MAX, _RATE_STATE_FILE)


# M3-T17: hot-reload config change callback — refreshes mutable config held by engines, no engine rebuild.
def _on_config_change(key: str, value: str) -> None:
    try:
        if key == "FUSION_MLX_MODEL" and mlx_client is not None:
            mlx_client.model = value
            logger.info("Hot-reloaded MLX model -> %s", value)
        elif key == "FUSION_K12_RATE_LIMIT":
            _rate_limiter._max = int(value)
            logger.info("Hot-reloaded rate limit cap -> %s/min", value)
        elif key == "FUSION_K12_SALT":
            try:
                # anonymizer is a module-level singleton defined later in the file (line ~1278), exists at runtime
                anonymizer.config.salt = value  # noqa: F821
                anonymizer.salt = anonymizer._salt_provider.get_salt()  # noqa: F821
                logger.info("Hot-reloaded desensitize salt (length %d)", len(value))
            except Exception as e:
                logger.warning("Salt hot-reload failed: %s", e)
        elif key == "FUSION_K12_LOG_LEVEL":
            logging.getLogger("fusion_k12_teacher").setLevel(value.upper())
            logger.info("Hot-reloaded log level -> %s", value.upper())
    except Exception as e:
        logger.warning("Failed to apply config change %s=%s: %s", key, value, e)


# M3-T17: start config provider polling + register callback. FileProvider is hot-reloadable, EnvProvider is a static no-op.
def _start_config_hot_reload() -> None:
    try:
        from .config import get_config
        cfg = get_config()
        cfg.on_change(_on_config_change)
        cfg.start()
    except Exception as e:
        logger.warning("Config hot-reload failed to start (config still usable, just no hot reload): %s", e)


# Stop the config polling thread.
def _stop_config_hot_reload() -> None:
    try:
        from .config import get_config
        get_config().stop()
    except Exception as e:
        logger.warning("Failed to stop config hot-reload: %s", e)


# ── #28: mlx health-probe watchdog — background periodic probe, alerts when backend hangs (observe only, no auto-restart) ──
_mlx_watch_task: asyncio.Task | None = None
_shell_registry_task: asyncio.Task | None = None


# Periodically probe the LLM backend (same source as /api/health: list_models). down -> WARNING, recovery -> INFO.
#
#     The mlx engine repeatedly hangs under sustained load (upstream issue) — the only signal used to be
#     generation requests starting to time out, invisible to ops. The watchdog makes a hang visible within one probe cycle.
async def _mlx_health_watchdog() -> None:
    interval = float(os.environ.get("FUSION_K12_HEALTH_PROBE_INTERVAL", "60"))
    cloud = False
    try:
        from .ai_client import _cloud_mode
        cloud = _cloud_mode()
    except Exception:
        pass
    logger.info("mlx health probe started (interval %ds, mode=%s)", int(interval), "cloud" if cloud else "local")
    was_down = False
    while True:
        await asyncio.sleep(interval)
        try:
            models = await mlx_client.list_models() if mlx_client is not None else None
            if cloud:
                # Cloud vendors behave inconsistently on /v1/models (filter by key permissions / return empty list) —
                # empty list does not count as down; only network/auth errors (raised exception) count as down
                down = models is None
            else:
                # When mlx hangs the gateway often returns 200 + empty list (not None) — empty list also counts as down
                down = not models
        except Exception:
            down = True
        if down and not was_down:
            hint = ("check cloud vendor API key/quota/network" if cloud
                    else "check fusion-mlx/gateway")
            logger.warning("Health alert: LLM backend unreachable — QA/lesson-script/scene generation will fail, %s", hint)
        elif not down and was_down:
            logger.info("Health alert cleared: LLM backend recovered")
        was_down = down


def _start_mlx_health_watchdog() -> None:
    global _mlx_watch_task
    _mlx_watch_task = asyncio.create_task(_mlx_health_watchdog())


def _stop_mlx_health_watchdog() -> None:
    global _mlx_watch_task
    if _mlx_watch_task is not None:
        _mlx_watch_task.cancel()
        _mlx_watch_task = None


def _drain_timeout() -> float:
    return float(os.environ.get("FUSION_K12_DRAIN_TIMEOUT", "30"))


# M3-T19: wait for in-flight requests to drain to zero, or force shutdown on timeout.
async def _drain_inflight() -> None:
    global _draining
    _draining = True
    if _inflight <= 0:
        logger.info("Drain complete: no in-flight requests")
        return
    timeout = _drain_timeout()
    logger.info("Drain started: %d in-flight requests, waiting up to %ss", _inflight, timeout)
    if _inflight_zero is None:
        return
    try:
        await asyncio.wait_for(_inflight_zero.wait(), timeout=timeout)
        logger.info("Drain complete: in-flight requests reached zero")
    except TimeoutError:
        logger.warning("Drain timed out after %ss, %d requests still in flight, forcing shutdown", timeout, _inflight)


# M3-T19: SIGTERM -> trigger graceful drain (uvicorn calls lifespan shutdown on SIGTERM,
#     here we additionally set _draining early to reject new requests, and log for ops visibility).
def _install_sigterm_handler() -> None:
    import signal
    try:
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGTERM, _on_sigterm)
        logger.info("SIGTERM drain handler registered")
    except (NotImplementedError, RuntimeError) as e:
        # Not the main loop or platform lacks add_signal_handler (Windows) — fall back to lifespan shutdown
        logger.warning("SIGTERM handler registration failed, drain relies on lifespan shutdown: %s", e)


# SIGTERM callback — mark draining, reject new requests. Actual shutdown is done by lifespan shutdown.
def _on_sigterm() -> None:
    global _draining, _ready
    _draining = True
    _ready = False
    logger.info("SIGTERM received, starting graceful drain (rejecting new requests, waiting for in-flight to finish)")


async def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def require_api_key(api_key: str = Security(_API_KEY_HEADER)) -> str:
    # R1: read env per request — key rotation takes effect without restart. SRV-1 fail-closed: reject all endpoints when unset.
    configured = os.environ.get("FUSION_K12_API_KEY", "")
    if not configured:
        # R3: misconfiguration (no key) uses 500, semantically separate from not-ready (503)/rate-limited (429) —
        # the old 503 made ops monitoring unable to distinguish "misconfigured" from "not ready", distorting alerts.
        logger.error("FUSION_K12_API_KEY not configured, rejecting protected endpoints (fail-closed)")
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
    # P1-5: sensitive-wordlist write operations (add/remove) require the admin key; regular keys cannot change global rules.
    # Admin key lives in its own env FUSION_K12_ADMIN_API_KEY; unset disables write endpoints (fail-closed).
    configured = os.environ.get("FUSION_K12_ADMIN_API_KEY", "")
    if not configured:
        logger.error("FUSION_K12_ADMIN_API_KEY not configured, rejecting sensitive-word writes (fail-closed)")
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
    # SRV-4: engines are None until lifespan completes, intercept startup-phase requests with 503
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
# P3: expose standards alignment/coverage report routes; previously only DifferentiationEngine used them internally.
standards_aligner: StandardsAligner | None = None
analytics_engine: AnalyticsEngine | None = None
content_filter: ContentFilter | None = None
sensitive_wordlist: SensitiveWordList | None = None
# Subject course platform (PRD math-doubao decoupling): SubjectRegistry holds subject modules, routes are subject-agnostic.
subject_registry: SubjectRegistry | None = None
# Classroom module (classroom PRD E1-E6, K1 text version): packs/sessions/judging/reports.
lesson_scripter = None
packager = None
session_manager = None
# Digital-human platform layer (K2/K3): DigitalHumanManager holds the 4-plugin pipeline, serve-lifetime singleton.
digital_human_manager = None
# Teacher identity + textbook catalog + resource library: user identity (X-Auth-Token) and textbook cascading-select data.
auth_service: AuthService | None = None
textbook_loader: TextbookLoader | None = None
_materials_repo = None  # materials persistence repo (reuses get_repository)
# SRV-4: engines are None until lifespan completes; _ready flag intercepts startup-phase requests
_ready: bool = False
# M3-T19: in-flight request counter — graceful shutdown waits for it to reach zero. asyncio is event-loop driven, but the counter is a plain int
# (no race on increment/decrement inside the single-threaded event loop). The drain-complete event wakes waiting coroutines.
_inflight: int = 0
_inflight_zero: asyncio.Event | None = None  # created lazily inside lifespan (needs the loop)
_draining: bool = False
# P1-8: single-instance lock — serve process-level mutex, prevents multiple workers/instances running the same engine+scheduler set concurrently.
# fcntl flock LOCK_EX|LOCK_NB: lock holder starts, non-holder is rejected at startup (applies uniformly to cli/serve/uvicorn --workers N).
_INSTANCE_LOCKFILE = os.environ.get(
    "FUSION_K12_INSTANCE_LOCK",
    os.path.expanduser("~/.fusion-k12/serve.lock"),
)
_instance_lockfd: int | None = None


def _is_cluster_mode() -> bool:
    # M2-T10: cluster mode allows horizontal multi-instance scale-out; the single-instance lock is standalone-only.
    return os.environ.get("FUSION_K12_MODE", "standalone").lower() == "cluster"


def _acquire_instance_lock() -> bool:
    global _instance_lockfd
    if _instance_lockfd is not None:
        return True
    # M2-T10: cluster mode coexists across instances, skip process-level mutex (cross-instance dedup relies on DB row locks, see scheduler T11).
    if _is_cluster_mode():
        logger.info("cluster mode, skipping single-instance lock (horizontal scale-out)")
        return True
    try:
        import fcntl
    except ImportError:
        logger.warning("fcntl unavailable, skipping single-instance lock")
        return True
    try:
        os.makedirs(os.path.dirname(_INSTANCE_LOCKFILE), exist_ok=True)
        fd = os.open(_INSTANCE_LOCKFILE, os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode())
        _instance_lockfd = fd
        logger.info("Acquired single-instance lock (pid=%d): %s", os.getpid(), _INSTANCE_LOCKFILE)
        return True
    except OSError:
        logger.error("Single-instance lock already held, another instance is running: %s — refusing to start", _INSTANCE_LOCKFILE)
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


# issue #17: runtime data retention policy — lazily purged at serve startup, prevents unbounded growth.
_MAT_RETENTION_DAYS = int(os.environ.get("FUSION_K12_MATERIAL_RETENTION_DAYS", "90"))
_MAT_MAX_PER_TEACHER = int(os.environ.get("FUSION_K12_MATERIAL_MAX_PER_TEACHER", "500"))
_UPLOAD_MAX_AGE_DAYS = int(os.environ.get("FUSION_K12_UPLOAD_RETENTION_DAYS", "90"))


# Purge old upload_*.json files — both data/ and fusion_k12_teacher/data/.
def _purge_old_uploads() -> int:
    import glob
    now = time.time()
    cutoff = now - _UPLOAD_MAX_AGE_DAYS * 86400
    purged = 0
    for pattern in ("data/upload_*.json", "fusion_k12_teacher/data/upload_*.json"):
        for fp in glob.glob(pattern):
            try:
                if os.path.getmtime(fp) < cutoff:
                    os.remove(fp)
                    purged += 1
            except OSError as e:
                logger.warning("Failed to purge upload file %s: %s", fp, e)
    if purged:
        logger.info("issue #17: purged %d expired upload files (>=%d days)", purged, _UPLOAD_MAX_AGE_DAYS)
    return purged


# Purge old material records — by age in days plus per-teacher cap.
def _purge_old_materials() -> int:
    if _materials_repo is None:
        return 0
    before_ts = ""
    if _MAT_RETENTION_DAYS > 0:
        import datetime
        cutoff = datetime.datetime.now() - datetime.timedelta(days=_MAT_RETENTION_DAYS)
        before_ts = cutoff.strftime("%Y-%m-%d %H:%M:%S")
    try:
        return _materials_repo.purge_old_materials(before_ts, _MAT_MAX_PER_TEACHER)
    except Exception as e:
        logger.warning("issue #17: material purge failed (does not affect startup): %s", e)
        return 0


def _init_teacher_services() -> None:
    # Teacher identity + textbook catalog + resource library: AuthService reuses the same repo as scheduler, textbook load builds the index.
    # issue #36: NonDegradableError raised by repo construction (cluster misconfig) must propagate and refuse startup —
    # silent degradation would let cluster instances each run SQLite (split-brain) while still reporting Healthy.
    global auth_service, textbook_loader, _materials_repo
    try:
        _materials_repo = get_repository()
        auth_service = AuthService(_materials_repo)
        textbook_loader = TextbookLoader()
        textbook_loader.load_all()
        logger.info(
            "Teacher identity + textbook + materials ready: editions=%d",
            len(textbook_loader.list_editions()),
        )
    except Exception as e:
        rethrow_if_fatal(e)
        logger.warning("Teacher identity/textbook init failed (generation still works, just no identity+materials): %s", e)
        auth_service = None
        textbook_loader = None
        _materials_repo = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global mlx_client, curriculum_engine, assessment_engine
    global subject_expert, personalization_engine, content_generator
    global differentiation_engine, standards_query, standards_loader, standards_aligner
    global analytics_engine, content_filter, sensitive_wordlist, subject_registry
    global lesson_scripter, packager, session_manager
    global digital_human_manager
    global _ready, _shell_registry_task
    # SRV-5: if build fails, yield never runs; use try/except to clean up already-allocated resources
    try:
        # P1-8: single-instance lock — refuse startup without the lock, prevents uvicorn --workers N instances running the same engine/scheduler set.
        if not _acquire_instance_lock():
            raise RuntimeError(f"single-instance lock already held: {_INSTANCE_LOCKFILE}")
        # A9: build_engines includes loader.load_all() synchronous disk I/O, run in a thread pool
        # to avoid blocking the event loop — first load of a large standards library takes hundreds of ms, otherwise all concurrent requests hang.
        bundle = await asyncio.to_thread(build_engines)
        # A14: registration separated from construction — the factory is pure construction, explicitly register the global registry here (agent executor looks up engines by name)
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
        # P3: build the aligner from the same bundle StandardsQuery, same instance as inside DifferentiationEngine.
        standards_aligner = StandardsAligner(query=bundle.standards_query)
        analytics_engine = bundle.analytics
        # P1-9: reuse the bundle-shared ContentFilter — one sensitive-word/age rule set, instead of serve-side
        # re-construction producing two divergent rule copies (engines.build_engines already injects the same instance into 7 engines).
        content_filter = bundle.content_filter
        sensitive_wordlist = SensitiveWordList()
        subject_registry = bundle.subject_registry
        # Classroom module (E1-E6 K1 text version): shares mlx_client, separate SQLite store.
        _classroom_store = ClassroomStore()
        lesson_scripter = LessonScripter(mlx_client)
        packager = Packager(_classroom_store)
        session_manager = SessionManager(_classroom_store)
        # Digital-human platform layer (K2/K3): inject mlx/registry/session_manager/scripter, prewarm plugins.
        digital_human_manager = DigitalHumanManager(
            mlx_client, subject_registry, session_manager, lesson_scripter,
        )
        await digital_human_manager.start()
        scheduler.load_default_tasks()
        scheduler.load_history()
        scheduler.start()
        _init_allowed_dirs()
        # Teacher identity + textbook catalog + resource library (issue #36: cluster misconfig fail-closed propagates and refuses startup)
        _init_teacher_services()
        _ready = True
        # M3-T13/T14: inject scheduler repo into the audit logger, enabling persistence.
        try:
            from .audit import get_audit_logger
            get_audit_logger().set_repo(getattr(scheduler, "_repo", None))
        except Exception as e:
            logger.warning("Failed to inject repo into audit logger (memory only): %s", e)
        # M3-T17: config hot-reload — start polling, register callback refreshing mutable engine config.
        _start_config_hot_reload()
        # #28: mlx health-probe watchdog — log alert within one probe cycle when the backend hangs
        _start_mlx_health_watchdog()
        # M3-T19: in-flight zero event (bound to current loop) + SIGTERM drain handling
        global _inflight_zero
        _inflight_zero = asyncio.Event()
        _install_sigterm_handler()
        # issue #17: lazily purge old upload files + old material records at startup
        _purge_old_uploads()
        _purge_old_materials()
        # issue #30: Union Web shell registration — env-gated, register web/manifest.json with the gateway and keep alive via heartbeat
        try:
            from .shell_registry import shell_registration_enabled, shell_registry_loop
            if shell_registration_enabled():
                _shell_registry_task = asyncio.create_task(shell_registry_loop())
                logger.info("shell gateway registration started (manifest=web/manifest.json)")
            else:
                logger.info("shell gateway registration not enabled (FUSION_SHELL_GATEWAY_URL / FUSION_ADMIN_KEY unset)")
        except Exception as e:
            logger.warning("shell registration failed to start (does not affect the service): %s", e)
        logger.info("Fusion-K12-Teacher API started, MLXClient initialized")
    except Exception as exc:
        logger.error("lifespan startup failed, cleaning up allocated resources: %s", exc, exc_info=True)
        _ready = False
        # R2: release the constructed mlx/scheduler and clear all engine globals —
        # after the original re-raise half the globals were assigned and half still None, leaving workers with half an engine set.
        try:
            await scheduler.aclose()
        except Exception as e:
            logger.warning("scheduler.aclose failed (startup-exception cleanup): %s", e)
        if mlx_client is not None:
            try:
                await mlx_client.close()
            except Exception as e:
                logger.warning("mlx_client.close failed (startup-exception cleanup): %s", e)
        # Clear engine globals to avoid half-initialized state lingering across restarts
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
    # M3-T19: graceful drain — reject new requests, wait for in-flight to reach zero or time out
    global _draining
    _draining = True
    await _drain_inflight()
    # M3-T17: stop the config polling thread
    _stop_config_hot_reload()
    # #28: stop the mlx health probe
    _stop_mlx_health_watchdog()
    # issue #30: stop the shell registration heartbeat
    if _shell_registry_task is not None:
        _shell_registry_task.cancel()
        try:
            await _shell_registry_task
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning("shell registration task raised during teardown: %s", e)
        _shell_registry_task = None
    # M3-T14: flush remaining audit events before shutdown
    try:
        from .audit import get_audit_logger
        await get_audit_logger().aclose()
    except Exception as e:
        logger.warning("Audit close flush failed: %s", e)
    try:
        await scheduler.aclose()
    except Exception as e:
        logger.warning("scheduler.aclose failed: %s", e)
    if digital_human_manager is not None:
        try:
            await digital_human_manager.aclose()
        except Exception as e:
            logger.warning("digital_human_manager.aclose failed: %s", e)
    if mlx_client is not None:
        try:
            await mlx_client.close()
        except Exception as e:
            logger.warning("mlx_client.close failed: %s", e)
    _release_instance_lock()


app = FastAPI(
    title="Fusion-K12-Teacher API",
    version=__version__,
    lifespan=lifespan,
)


# SRV-2: sliding-window rate limiting, prevents a single client from overwhelming local inference resources.
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        key = await _client_key(request)
        if not await _rate_limiter.check(key):
            # SRV-6: use a standard JSONResponse instead of HTTPException, ensuring a unified error body through the normal response chain
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": f"rate limit exceeded ({_RATE_MAX}/{_RATE_WINDOW}s)"},
            )
    return await call_next(request)


# M3-T13: audit instrumentation — generate a trace_id per request, record route/method/status/duration.
#
#     trace_id is propagated to the X-Trace-Id response header; student identifier hash is extracted from the request body student_id field.
#     Probe/metrics endpoints are excluded (no audit needed). Audit events are recorded asynchronously into AuditLogger (T14 persistence).
@app.middleware("http")
async def audit_middleware(request: Request, call_next):
    path = request.url.path
    if not path.startswith("/api/") or path in ("/api/health", "/api/ready", "/api/metrics"):
        return await call_next(request)
    from .audit import AuditEvent, get_audit_logger, new_trace_id
    # M3-T19: reject new business requests during graceful drain (probes excluded, allowed above)
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
    # M3-T19: in-flight +1, then -1 on completion and notify drain waiters
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
        # M3-T16: metrics collection — request counter + latency histogram
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
            logger.warning("Failed to record audit event (does not affect the request): %s", e)


# Generation route -> material type mapping (content/generate is dynamic, decided by the response type field).
# issue #14: fire-and-forget tasks must hold a strong reference, otherwise the event loop holds only a weak reference and the task can be GC'd,
# with exceptions only printed at GC time as "Task exception was never retrieved" — spawn uniformly via _spawn_bg_task.
_bg_tasks: set[asyncio.Task] = set()


# Spawn a background task holding a strong reference — auto-removed when done, exceptions go to structured logs.
def _spawn_bg_task(coro) -> asyncio.Task:
    task = asyncio.ensure_future(coro)
    _bg_tasks.add(task)

    def _done(t: asyncio.Task) -> None:
        _bg_tasks.discard(t)
        if not t.cancelled() and t.exception() is not None:
            logger.warning("Background task exception: %s", t.exception())

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
        logger.info("Material saved: teacher=%s type=%s title=%s", teacher_id, mtype, title)
    except Exception as e:
        logger.warning("Material save failed (does not affect the response): %s", e)


# After a generation route succeeds, if X-Auth-Token is present, auto-save the material to the resource library.
#
#     Reads the request body (cached so downstream can still read it) + response body; skips non-200 or non-generation routes.
@app.middleware("http")
async def auto_save_material_middleware(request: Request, call_next):
    path = request.url.path
    if request.method != "POST" or path not in _GEN_ROUTE_TYPES:
        return await call_next(request)
    token = request.headers.get("X-Auth-Token", "")
    # Pre-read and cache the request body for reuse by the downstream handler + this middleware (Starlette caches _body).
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
    # BaseHTTPMiddleware responses are streaming; the body_iterator must be consumed and the response rebuilt to read the body.
    body_chunks: list[bytes] = []
    try:
        async for chunk in response.body_iterator:
            body_chunks.append(chunk)
    except Exception:
        return response
    resp_bytes = b"".join(body_chunks)
    # Rebuild the response (keeping status/headers), otherwise downstream cannot read the body after consumption.
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
    # SRV-9: when an engine gracefully degrades and returns a result containing error, respond with explicit 502 instead of misleading 200+error
    err = getattr(result, "error", None)
    if not err and isinstance(result, dict):
        err = result.get("error")
    if err:
        logger.warning("%s engine failed: %s", label, err)
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

# i18n: user-facing (OpenAPI field descriptions)
class CurriculumPlanRequest(BaseModel):
    grade: GradeField = Field(..., description="年级")
    subject: str = Field(..., max_length=20, description="学科")
    topic: str = Field(..., max_length=100, description="主题")

# i18n: user-facing (OpenAPI field descriptions)
class AssessmentGradeRequest(BaseModel):
    question: str = Field(..., max_length=2000, description="题目")
    answer: str = Field(..., max_length=2000, description="学生答案")
    standard: str = Field("", max_length=2000, description="参考答案/评分标准")

# i18n: user-facing (OpenAPI field descriptions)
class SubjectExplainRequest(BaseModel):
    subject: str = Field(..., max_length=20, description="学科")
    grade: GradeField = Field("", description="年级")
    concept: str = Field(..., max_length=500, description="概念/问题")

# i18n: user-facing (OpenAPI field descriptions)
class PersonalizePathRequest(BaseModel):
    student_id: str = Field(..., max_length=50, description="学生ID")
    progress: dict[str, Any] = Field(default_factory=dict, description="学习进度")

    # SRV-7: bound progress key count and value length, guards against oversized payloads
    @model_validator(mode="after")
    def _bound_progress(self):
        if len(self.progress) > 20:
            raise ValueError("progress has more than the maximum of 20 keys")
        for k, v in self.progress.items():
            if len(str(k)) > 50:
                raise ValueError("progress key too long")
            if isinstance(v, str) and len(v) > 500:
                raise ValueError("progress value too long")
        return self

# i18n: user-facing (OpenAPI field descriptions)
class ContentGenerateRequest(BaseModel):
    topic: str = Field(..., max_length=100, description="主题")
    grade: GradeField = Field("", description="年级")
    style: str = Field("interactive", max_length=20, description="生成风格")


# ── Teacher identity ──

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


# Soft identity — verify and return teacher_id when a token is present, otherwise None (not persisted in api_key-only mode).
async def get_optional_teacher(
    x_auth_token: str = Security(_AUTH_TOKEN_HEADER),
) -> str | None:
    if not x_auth_token or not auth_service:
        return None
    try:
        return await asyncio.to_thread(auth_service.verify_token, x_auth_token)
    except Exception:
        return None


# Hard identity — a valid token is required, otherwise 401. Used by /me, /logout, and materials read/write.
async def require_teacher(
    x_auth_token: str = Security(_AUTH_TOKEN_HEADER),
) -> str:
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


# ── Textbook catalog ──

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


# ── Materials library ──

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
    # P1-10: health probes backend fusion-mlx reachability, not a static response.
    # /api/health = liveness (process alive) + backend probe; /api/ready = readiness (engines ready).
    backend = "unknown"
    model_id = ""
    if mlx_client is not None:
        try:
            # list_models is async, await directly (has built-in cache+lock); to_thread would drop the await and return a pending coroutine
            models = await mlx_client.list_models()
            backend = "ok" if models is not None else "down"
            # issue acceptance: show the configured model even for an empty models list (gateway response parse errors etc.) —
            # previously model_id was inside if models:, so health always showed "" on empty lists, misleading ops
            model_id = mlx_client.model or "(pending)"
        except Exception as e:
            logger.warning("health: fusion-mlx probe failed: %s", e)
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
    # P1-10: readiness — 200 when all engines are ready, else 503. For K8s readinessProbe / Docker HEALTHCHECK.
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
    # M3-T15: audit export — admin key, JSON/CSV. Limit capped at 10000 to guard oversized responses.
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
        logger.warning("Audit export read failed: %s", e)
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
    # M3-T16: Prometheus metrics endpoint — exposition format, admin key.
    # Probe/audit middleware already exclude this endpoint (path whitelist).
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
    # i18n: user-facing (product defaults feeding content generation)
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
    # i18n: user-facing ("综合" is the cross-subject subject name passed to content generation)
    if req.style == "flashcards":
        result = await content_generator.generate_flashcards(
            subject="综合", grade=req.grade or "3", topic=req.topic,
        )
        # P3: flashcards degrade returns an empty list -> explicit 502, consistent with worksheet/game, never a silent 200 empty object
        if not result:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="flashcards generation failed")
        return {"type": "flashcards", "items": result}
    elif req.style == "slides":
        result = await content_generator.generate_lesson_slides(
            subject="综合", grade=req.grade or "3", topic=req.topic,
        )
        # P3: slides degrade returns an empty list -> 502, unified semantics
        if not result:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="slides generation failed")
        return {"type": "slides", "items": result}
    elif req.style == "game":
        result = await content_generator.generate_educational_game(
            subject="综合", grade=req.grade or "3", topic=req.topic,
        )
        # SRV-8: generation failure (with error field) no longer silently returns a 200 empty object; explicit 502 so the client notices
        if result.get("error"):
            logger.warning("content/generate game failed: %s", result.get("error"))
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="game generation failed",
            )
        # CNT-1: whitelist field passthrough, internal error not leaked; the LLM's type does not override the response type
        safe = {k: v for k, v in result.items() if k not in ("error", "type")}
        return {"type": "game", "game_type": result.get("type", ""), **safe}
    else:
        ws = await content_generator.generate_worksheet(
            subject="综合", grade=req.grade or "3", topic=req.topic,
        )
        # A13: worksheet failure uniformly converted to 502, error stays out of the 200 body —
        # returning 200 + ws.error leaked internal error details, contradicting the _check_engine_error conversion design.
        _check_engine_error(ws, "content/worksheet")
        return {
            "type": "worksheet",
            "title": ws.title,
            "sections": ws.sections,
            "answer_key": ws.answer_key,
            "instructions": ws.instructions,
        }


# ── Assessment extensions (P1-13: add essay/report/rubric routes) ──

# i18n: user-facing (OpenAPI field descriptions)
class AssessmentEssayRequest(BaseModel):
    essay: str = Field(..., max_length=5000, description="学生作文")

# i18n: user-facing (OpenAPI field descriptions)
class AssessmentReportRequest(BaseModel):
    student: str = Field(..., max_length=50, description="学生姓名/ID")
    subject: str = Field(..., max_length=20, description="学科")
    grade: GradeField = Field(..., description="年级")
    history: list[dict[str, Any]] = Field(default_factory=list, max_length=50, description="学习记录")

# i18n: user-facing (OpenAPI field descriptions)
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


# ── Subject extensions (P1-14: add exercise/stem_project/language_activity routes) ──

# i18n: user-facing (OpenAPI field descriptions)
class SubjectExerciseRequest(BaseModel):
    subject: str = Field(..., max_length=20, description="学科")
    grade: GradeField = Field(..., description="年级")
    topic: str = Field(..., max_length=100, description="主题")
    difficulty: str = Field("medium", max_length=20, description="难度 easy/medium/hard")

# i18n: user-facing (OpenAPI field descriptions)
class SubjectStemRequest(BaseModel):
    grade: GradeField = Field(..., description="年级")
    topic: str = Field(..., max_length=100, description="主题")
    duration: str = Field("2课时", max_length=20, description="时长")

# i18n: user-facing (OpenAPI field descriptions)
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
    # P3: degrade path now sets .error, triggering 502 instead of 200 + a generation-failed question string
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


# ── Curriculum extensions (P1-15: add quiz/unit_plan routes) ──

# i18n: user-facing (OpenAPI field descriptions)
class CurriculumQuizRequest(BaseModel):
    grade: GradeField = Field(..., description="年级")
    subject: str = Field(..., max_length=20, description="学科")
    topic: str = Field(..., max_length=100, description="主题")
    num_questions: int = Field(10, ge=1, le=50, description="题目数量")

# i18n: user-facing (OpenAPI field descriptions)
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


# ── Personalize extensions (P1-16: add diagnose/recommend routes) ──

# i18n: user-facing (OpenAPI field descriptions)
class PersonalizeDiagnoseRequest(BaseModel):
    subject: str = Field(..., max_length=20, description="学科")
    grade: GradeField = Field(..., description="年级")
    responses: list[dict[str, Any]] = Field(default_factory=list, max_length=50, description="答题记录")

# i18n: user-facing (OpenAPI field descriptions)
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


# ── Content extensions (parent_communication route) ──

# i18n: user-facing (OpenAPI field descriptions)
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
    # generate_parent_communication failure returns an empty string (CNT-2: never leak errors); empty string means failure -> 502
    if not result:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="parent communication failed")
    return {"content": result}


# ── Request Models (v0.3) ──

# i18n: user-facing (OpenAPI field descriptions)
class DifferentiatedPlanRequest(BaseModel):
    subject: str = Field(..., max_length=20, description="学科")
    grade: GradeField = Field(..., description="年级")
    topic: str = Field(..., max_length=100, description="主题")
    duration: int = Field(45, ge=5, le=240, description="课时(分钟)")

# i18n: user-facing (OpenAPI field descriptions)
class DifferentiatedQuizRequest(BaseModel):
    subject: str = Field(..., max_length=20, description="学科")
    grade: GradeField = Field(..., description="年级")
    topic: str = Field(..., max_length=100, description="主题")
    num_questions: int = Field(5, ge=1, le=50, description="每层题目数量")

# i18n: user-facing (OpenAPI field descriptions)
class StandardsQueryRequest(BaseModel):
    subject: str = Field(..., max_length=20, description="学科")
    grade: GradeField = Field(..., description="年级")
    topic: str = Field("", max_length=100, description="主题关键词")


# ── Standards (v0.3) ──

# List curriculum-standard knowledge points.
@app.get("/api/standards/list")
async def standards_list(subject: str = "", grade: str = "", _: str = Depends(require_api_key)):
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


# Query curriculum-standard knowledge points.
@app.post("/api/standards/query")
async def standards_query_endpoint(req: StandardsQueryRequest, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    logger.info("standards/query: subject=%s grade=%s topic=%s", req.subject, req.grade, req.topic)
    if req.topic:
        points = standards_query.find_by_topic(req.subject, req.grade, req.topic)
    else:
        points = standards_query.get_knowledge_points(req.subject, req.grade)
    return {
        "total": len(points),
        "knowledge_points": [p.to_dict() for p in points],
    }


# P3: expose standards alignment/coverage reports — previously only DifferentiationEngine used them internally, with no direct CLI/serve route.
# i18n: user-facing (OpenAPI field descriptions)
class StandardsAlignRequest(BaseModel):
    subject: str = Field(..., max_length=20, description="学科")
    grade: GradeField = Field(..., description="年级")
    topic: str = Field(..., max_length=100, description="主题")


# i18n: user-facing (OpenAPI field descriptions)
class StandardsCoverageRequest(BaseModel):
    subject: str = Field(..., max_length=20, description="学科")
    grade: GradeField = Field(..., description="年级")
    objectives: list[str] = Field(..., min_length=1, max_length=50, description="教学目标")


# i18n: user-facing (OpenAPI field descriptions)
class StandardsRemediateRequest(BaseModel):
    subject: str = Field(..., max_length=20, description="学科")
    grade: GradeField = Field(..., description="年级")
    topic: str = Field("", max_length=100, description="课题")
    missing_points: list[str] = Field(..., min_length=1, max_length=30, description="缺失知识点ID列表")


# Standards alignment — returns knowledge points / must-cover / optional-advanced / prerequisites for the topic.
@app.post("/api/standards/align")
async def standards_align(req: StandardsAlignRequest, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
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


# Standards coverage report — validates how well teaching objectives cover the knowledge points.
@app.post("/api/standards/coverage")
async def standards_coverage(req: StandardsCoverageRequest, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
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


# Generate a remediation teaching plan for missing knowledge points — no learner data needed, based on standard knowledge points + prerequisites.
@app.post("/api/standards/remediate")
async def standards_remediate(req: StandardsRemediateRequest, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
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
        return {"subject": req.subject, "grade": req.grade, "topic": req.topic, "missing_points": [], "strategies": [], "error": "missing knowledge points could not be resolved"}
    import json as _json
    details_json = _json.dumps(missing_details, ensure_ascii=False)
    # i18n: user-facing (LLM prompt)
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
            # i18n: user-facing (LLM system prompt)
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
        llm_err = "LLM returned empty or unparseable output"
    except Exception as e:
        logger.error("standards/remediate LLM failed: %s", e)
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

# Generate a three-tier differentiated lesson plan.
@app.post("/api/curriculum/plan-diff")
async def curriculum_plan_diff(req: DifferentiatedPlanRequest, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    logger.info("curriculum/plan-diff: subject=%s grade=%s topic=%s", req.subject, req.grade, req.topic)
    result = await differentiation_engine.generate_differentiated_lesson(
        subject=req.subject, grade=req.grade, topic=req.topic, duration=req.duration,
    )
    _check_engine_error(result, "curriculum/plan-diff")
    return result.to_dict()


# Generate a three-tier differentiated quiz.
@app.post("/api/curriculum/quiz-diff")
async def curriculum_quiz_diff(req: DifferentiatedQuizRequest, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    logger.info("curriculum/quiz-diff: subject=%s grade=%s topic=%s", req.subject, req.grade, req.topic)
    result = await differentiation_engine.generate_differentiated_quiz(
        subject=req.subject, grade=req.grade, topic=req.topic, num_questions=req.num_questions,
    )
    _check_engine_error(result, "curriculum/quiz-diff")
    return result.to_dict()


# ── Request Models (v0.4) ──

# i18n: user-facing (OpenAPI field descriptions)
class ClassProfileRequest(BaseModel):
    class_id: str = Field(..., max_length=50, description="班级ID")
    subject: str = Field(..., max_length=20, description="学科")
    grade: GradeField = Field(..., description="年级")
    data_path: str = Field("", max_length=500, description="评估数据文件路径(JSON/CSV)")

# i18n: user-facing (OpenAPI field descriptions)
class StudentProfileRequest(BaseModel):
    student_id: str = Field(..., max_length=50, description="学生ID")
    subject: str = Field(..., max_length=20, description="学科")
    grade: GradeField = Field(..., description="年级")
    data_path: str = Field("", max_length=500, description="评估数据文件路径(JSON/CSV)")

# i18n: user-facing (OpenAPI field descriptions)
class ErrorAnalysisRequest(BaseModel):
    subject: str = Field(..., max_length=20, description="学科")
    grade: GradeField = Field(..., description="年级")
    data_path: str = Field("", max_length=500, description="评估数据文件路径(JSON/CSV)")

# i18n: user-facing (OpenAPI field descriptions)
class RemedialPlanRequest(BaseModel):
    student_id: str = Field(..., max_length=50, description="学生ID")
    subject: str = Field(..., max_length=20, description="学科")
    grade: GradeField = Field(..., description="年级")
    data_path: str = Field("", max_length=500, description="评估数据文件路径(JSON/CSV)")

# i18n: user-facing (OpenAPI field descriptions)
class ClassReportRequest(BaseModel):
    class_id: str = Field(..., max_length=50, description="班级ID")
    subject: str = Field(..., max_length=20, description="学科")
    grade: GradeField = Field(..., description="年级")
    data_path: str = Field("", max_length=500, description="评估数据文件路径(JSON/CSV)")

# i18n: user-facing (OpenAPI field descriptions)
class AnalyticsUploadRequest(BaseModel):
    data: list[dict[str, Any]] = Field(..., max_length=1000, description="评估数据(JSON数组)")
    format: str = Field("json", max_length=10, description="数据格式: json")

    # P2: per-record size was unbounded -> giant records exhaust memory. Cap JSON-serialized bytes per record.
    _MAX_RECORD_BYTES = 64 * 1024

    @model_validator(mode="after")
    def _bound_record_size(self):
        import json as _j
        for i, rec in enumerate(self.data):
            try:
                size = len(_j.dumps(rec, ensure_ascii=False))
            except (TypeError, ValueError):
                raise ValueError(f"record #{i} is not serializable")
            if size > self._MAX_RECORD_BYTES:
                raise ValueError(f"record #{i} exceeds the per-record limit of {self._MAX_RECORD_BYTES} bytes (actual {size})")
        return self

# i18n: user-facing (OpenAPI field descriptions)
class ContentWorksheetDiffRequest(BaseModel):
    subject: str = Field(..., max_length=20, description="学科")
    grade: GradeField = Field(..., description="年级")
    topic: str = Field(..., max_length=100, description="主题")
    num_questions: int = Field(8, ge=1, le=50, description="每层题目数量")


_ALLOWED_DATA_DIRS: list[Path] = []

# issue #17: rolling retention cap for uploaded files — oldest files removed by mtime beyond the cap, prevents unbounded disk growth
_UPLOAD_KEEP = int(os.environ.get("FUSION_K12_UPLOAD_KEEP", "500"))


# Rolling cleanup of upload_*.json — keep only the newest `keep` files; failures do not affect the upload flow.
def _sweep_upload_files(dest_dir: Path, keep: int = _UPLOAD_KEEP) -> None:
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
        logger.warning("upload sweep failed (upload unaffected): %s", e)


def _init_allowed_dirs():
    # R7: single source of truth — reuse analytics.loader._allowed_data_dirs(), no more serve-side duplicate definition.
    # The old two allowed-directory sources diverged; updating one and forgetting the other broke or over-tightened path validation.
    from .analytics.loader import _allowed_data_dirs
    global _ALLOWED_DATA_DIRS
    _ALLOWED_DATA_DIRS = _allowed_data_dirs()
    logger.info("allowed data dirs: %s", [str(d) for d in _ALLOWED_DATA_DIRS])


# Validate that data_path is inside an allowed directory (SRV-5: exact is_relative_to match, not prefix).
#
#     AGT-2/R7: reuse the loader.validate_data_path whitelist so CLI/tasks/serve validate from the same source.
def _check_allowed_path(path: str) -> Path:
    try:
        from .analytics.loader import DataPathError, validate_data_path
        return validate_data_path(path)
    except DataPathError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


# SRV-4: run synchronous file I/O in a thread pool so the event loop is not blocked.
async def _load_assessments(path: str):
    if not path:
        return []
    _check_allowed_path(path)
    if path.endswith(".csv"):
        return await asyncio.to_thread(load_from_csv, path)
    return await asyncio.to_thread(load_from_json, path)


# ── Analytics (v0.4) ──

# Generate a class learning profile.
@app.post("/api/analytics/class-profile")
async def analytics_class_profile(req: ClassProfileRequest, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    logger.info("analytics/class-profile: class=%s subject=%s grade=%s", req.class_id, req.subject, req.grade)
    assessments = await _load_assessments(req.data_path)
    profile = await analytics_engine.build_class_profile(
        class_id=req.class_id, subject=req.subject, grade=req.grade, assessments=assessments,
    )
    _check_engine_error(profile, "analytics/class-profile")
    return profile.to_dict()


# Generate an individual student profile.
@app.post("/api/analytics/student-profile")
async def analytics_student_profile(req: StudentProfileRequest, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    logger.info("analytics/student-profile: student=%s subject=%s grade=%s", _mask_sid(req.student_id), req.subject, req.grade)
    all_assessments = await _load_assessments(req.data_path)
    history = [a for a in all_assessments if a.student_id == req.student_id]
    profile = await analytics_engine.build_student_profile(
        student_id=req.student_id, subject=req.subject, grade=req.grade, history=history,
    )
    _check_engine_error(profile, "analytics/student-profile")
    return profile.to_dict()


# Error attribution analysis.
@app.post("/api/analytics/error-analysis")
async def analytics_error_analysis(req: ErrorAnalysisRequest, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    logger.info("analytics/error-analysis: subject=%s grade=%s", req.subject, req.grade)
    all_assessments = await _load_assessments(req.data_path)
    responses = []
    for a in all_assessments:
        responses.extend(a.responses)
    errors = await analytics_engine.analyze_errors(
        subject=req.subject, grade=req.grade, responses=responses,
    )
    # P2: analyze_errors degrade returns a fallback entry with error_id=err-fallback; check the error pass-through failure status.
    # i18n: user-facing (compares against the analytics engine's fallback root_cause string)
    if errors and getattr(errors[0], "error_type", "") == "unknown" and errors[0].root_cause == "分析失败，需人工检查":
        logger.warning("analytics/error-analysis degraded to fallback")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="error-analysis failed",
        )
    return {"total": len(errors), "errors": [e.to_dict() for e in errors]}


# Generate a remedial teaching plan.
@app.post("/api/analytics/remedial")
async def analytics_remedial(req: RemedialPlanRequest, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    logger.info("analytics/remedial: student=%s subject=%s grade=%s", _mask_sid(req.student_id), req.subject, req.grade)
    all_assessments = await _load_assessments(req.data_path)
    history = [a for a in all_assessments if a.student_id == req.student_id]
    student_profile = await analytics_engine.build_student_profile(
        student_id=req.student_id, subject=req.subject, grade=req.grade, history=history,
    )
    _check_engine_error(student_profile, "analytics/student-profile")
    # P2: no longer fabricate error_rate=0.5 out of thin air — derive real weak points from knowledge_mastery.
    # Mastery < 60 counts as weak, error_rate = 1 - mastery/100; no weak points returns an empty plan (rather than feeding fake data).
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


# Generate a class learning report (Markdown).
@app.post("/api/analytics/class-report")
async def analytics_class_report(req: ClassReportRequest, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    logger.info("analytics/class-report: class=%s subject=%s grade=%s", req.class_id, req.subject, req.grade)
    assessments = await _load_assessments(req.data_path)
    profile = await analytics_engine.build_class_profile(
        class_id=req.class_id, subject=req.subject, grade=req.grade, assessments=assessments,
    )
    _check_engine_error(profile, "analytics/class-profile")
    report = await analytics_engine.generate_class_report(profile)
    return {"class_id": req.class_id, "report": report}


# Learning analytics data JSON template — two students each with scores/responses, upload-ready for validation.
@app.get("/api/analytics/template/json")
async def analytics_template_json(_: str = Depends(require_api_key)):
    logger.info("analytics/template/json: returning JSON template")
    # i18n: user-facing (sample assessment data)
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


# Learning analytics data CSV template — one answer record per row, aggregated by student_id+assessment_id.
@app.get("/api/analytics/template/csv")
async def analytics_template_csv(_: str = Depends(require_api_key)):
    logger.info("analytics/template/csv: returning CSV template")
    # i18n: user-facing (sample assessment data)
    csv = (
        "student_id,student_name,assessment_id,date,subject,grade,total_score,max_score,question_id,question,student_answer,correct_answer,correct\n"
        "S001,张小明,A2026001,2026-09-20,数学,3,88,100,Q1,1/2的含义?,一半,把整体平均分2份取1份,true\n"
        "S001,张小明,A2026001,2026-09-20,数学,3,88,100,Q2,1/3和1/4谁大?,1/4,1/3,false\n"
        "S002,李小红,A2026001,2026-09-20,数学,3,95,100,Q1,1/2的含义?,整体均分2份取1份,把整体平均分2份取1份,true\n"
        "S002,李小红,A2026001,2026-09-20,数学,3,95,100,Q2,1/3和1/4谁大?,1/3,1/3,true\n"
    )
    headers = {"Content-Disposition": "attachment; filename=analytics_template.csv"}
    return PlainTextResponse(content=csv, media_type="text/csv", headers=headers)


# Upload learning analytics data — persisted to an allowed directory and the path returned for later analytics calls (SRV-6).
#
#     R6: minors' names are force-anonymized before persisting (PII never stored in plaintext); per-record schema validation rejects malformed injection;
#     logs record only counts and file names, never absolute paths.
@app.post("/api/analytics/upload")
async def analytics_upload(req: AnalyticsUploadRequest, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    logger.info("analytics/upload: %d records, format=%s", len(req.data), req.format)
    if req.format != "json":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="only json format supported",
        )
    # R6: upload entry force-anonymizes — student_name becomes a masked ID before persisting, minors' PII never stored in plaintext.
    # P2: fields_to_mask uses the full default set (phone/email/id_number/address masked too), no longer only student_name.
    # Shared anonymizer singleton: repeated uploads of the same student name yield the same mask, easing analytics correlation.
    anonymizer = DataAnonymizer(DesensitizeConfig())
    assessments = []
    rejected = 0
    for idx, item in enumerate(req.data):
        # R6: per-record schema validation — non-dict / missing student_id / out-of-range total_score rejected, malformed input never silently swallowed.
        if not isinstance(item, dict):
            rejected += 1
            logger.warning("analytics/upload: record #%d not a dict, rejected", idx)
            continue
        sid = item.get("student_id", "")
        if not sid or not isinstance(sid, str):
            rejected += 1
            logger.warning("analytics/upload: record #%d missing student_id, rejected", idx)
            continue
        total = item.get("total_score", 0.0)
        max_score = item.get("max_score", 100.0)
        try:
            if float(total) < 0 or float(max_score) <= 0:
                rejected += 1
                logger.warning("analytics/upload: record #%d score out of range (total=%s max=%s), rejected", idx, total, max_score)
                continue
        except (TypeError, ValueError):
            rejected += 1
            logger.warning("analytics/upload: record #%d score not numeric, rejected", idx)
            continue
        try:
            # R6: student_name built via anonymizer masking, persisted as masked ID
            raw_name = str(item.get("student_name", "") or "")
            anon_name = anonymizer.anonymize_name(raw_name, seq=str(idx)) if raw_name else ""
            # P2: responses contain raw student answers (PII); student_answer fields are anonymized before persisting, never stored in plaintext.
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
            logger.warning("analytics/upload: record #%d construction failed, rejected: %s", idx, e)
    import json as _json
    dest_dir = _ALLOWED_DATA_DIRS[0] if _ALLOWED_DATA_DIRS else Path.cwd() / "data"
    dest_dir.mkdir(parents=True, exist_ok=True)
    import time as _time
    dest = dest_dir / f"upload_{int(_time.time())}.json"

    def _write():
        with open(dest, "w", encoding="utf-8") as f:
            _json.dump([a.to_dict() for a in assessments], f, ensure_ascii=False, indent=2)

    await asyncio.to_thread(_write)
    # issue #17: rolling cleanup of uploaded files — keep only the newest N, prevents unbounded disk growth on long runs
    await asyncio.to_thread(_sweep_upload_files, dest_dir)
    # R6: logs record only counts and file names, never absolute paths (prevents path information leakage)
    logger.info("analytics/upload: persisted %d records (rejected %d) -> %s", len(assessments), rejected, dest.name)
    return {
        "accepted": len(assessments),
        "rejected": rejected,
        "total": len(req.data),
        # SRV-10: return only the file name, never the server-side absolute path
        "filename": dest.name,
    }


# ── Content worksheet-diff (v1.0) ──

# Generate a three-tier differentiated worksheet.
@app.post("/api/content/worksheet-diff")
async def content_worksheet_diff(req: ContentWorksheetDiffRequest, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    logger.info("content/worksheet-diff: subject=%s grade=%s topic=%s", req.subject, req.grade, req.topic)
    result = await differentiation_engine.generate_differentiated_worksheet(
        subject=req.subject, grade=req.grade, topic=req.topic, num_questions=req.num_questions,
    )
    _check_engine_error(result, "content/worksheet-diff")
    return result.to_dict()


# ── Request Models (v0.5) ──

# i18n: user-facing (OpenAPI field descriptions)
class AgentRunRequest(BaseModel):
    task_id: str = Field(..., max_length=50, description="任务ID")
    subject: str = Field("数学", max_length=20, description="学科")
    grade: GradeField = Field("3", description="年级")
    data_path: str = Field("", max_length=500, description="评估数据文件路径(每次执行重新加载, 避免过期数据)")

# i18n: user-facing (OpenAPI field descriptions)
class AgentScheduleRequest(BaseModel):
    task_id: str = Field(..., max_length=50, description="任务ID")
    enable: bool = Field(True, description="启用/禁用")


# ── Agent (v0.5) ──

# List available tasks.
@app.get("/api/agent/tasks")
async def agent_list_tasks(_: str = Depends(require_api_key)):
    tasks = list_available_tasks()
    registered = scheduler.list_tasks()
    return {
        "predefined": tasks,
        "registered": [t.to_dict() for t in registered],
    }


# Run a task immediately — built fresh from request parameters each call, avoiding shared _tasks cross-request pollution (SRV-7).
#
#     data_path is passed in and reloaded every call, so stale data is never baked in at task-build time (AGT-5).
@app.post("/api/agent/run")
async def agent_run_task(req: AgentRunRequest, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    logger.info("agent/run: task_id=%s subject=%s grade=%s", req.task_id, req.subject, req.grade)
    run_kwargs = {"subject": req.subject, "grade": req.grade}
    if req.data_path:
        _check_allowed_path(req.data_path)
        run_kwargs["data_path"] = req.data_path
    result = await scheduler.run_task(req.task_id, **run_kwargs)
    _check_engine_error(result, "agent/run")
    return result.to_dict()


# Enable/disable task scheduling.
@app.post("/api/agent/schedule")
async def agent_schedule_task(req: AgentScheduleRequest, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    logger.info("agent/schedule: task_id=%s enable=%s", req.task_id, req.enable)
    if req.enable:
        ok = scheduler.enable_task(req.task_id)
    else:
        ok = scheduler.disable_task(req.task_id)
    return {"task_id": req.task_id, "enabled": req.enable, "success": ok}


# View execution history.
@app.get("/api/agent/history")
async def agent_history(limit: int = 20, _: str = Depends(require_api_key)):
    history = scheduler.get_history(limit=limit)
    return {"total": len(history), "history": [r.to_dict() for r in history]}


# ── Request Models (v0.6) ──

# i18n: user-facing (OpenAPI field descriptions)
class SafetyCheckRequest(BaseModel):
    text: str = Field(..., max_length=10000, description="待检查文本")
    grade: Annotated[str, BeforeValidator(_coerce_str)] = Field("3", pattern=r"^[1-9]$|^1[0-2]$", description="目标年级 1-12")

# i18n: user-facing (OpenAPI field descriptions)
class SafetyFilterRequest(BaseModel):
    text: str = Field(..., max_length=10000, description="待过滤文本")

# i18n: user-facing (OpenAPI field descriptions)
class SafetyWordlistRequest(BaseModel):
    word: str = Field(..., max_length=100, description="敏感词")
    action: str = Field("add", max_length=10, description="add 或 remove")


# ── Safety (v0.6) ──

# Check content safety.
@app.post("/api/safety/check")
async def safety_check(req: SafetyCheckRequest, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    logger.info("safety/check: grade=%s text=%s...", req.grade, req.text[:30])
    result = content_filter.check_text(req.text, req.grade)
    return result.to_dict()


# Filter sensitive words.
@app.post("/api/safety/filter")
async def safety_filter(req: SafetyFilterRequest, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    logger.info("safety/filter: text=%s...", req.text[:30])
    filtered = content_filter.filter_sensitive(req.text)
    return {"filtered_text": filtered}


# Manage the sensitive-word list.
@app.post("/api/safety/wordlist")
async def safety_wordlist(
    req: SafetyWordlistRequest,
    _: str = Depends(require_admin_api_key),
    _r: None = Depends(_require_ready),
):
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


# List the sensitive-word list.
@app.get("/api/safety/wordlist")
async def safety_wordlist_list(_: str = Depends(require_api_key)):
    return {"count": sensitive_wordlist.count, "words": sensitive_wordlist.list_words()}


# ── Request Models (v0.6 desensitize) ──

# i18n: user-facing (OpenAPI field descriptions)
class DesensitizeAnonRequest(BaseModel):
    records: list[dict[str, Any]] = Field(..., max_length=1000, description="待脱敏记录列表")
    name_mode: str = Field("id", max_length=10, description="匿名模式: id/mask")
    id_prefix: str = Field("S", max_length=10, description="ID前缀")

# i18n: user-facing (OpenAPI field descriptions)
class DesensitizeExportRequest(BaseModel):
    records: list[dict[str, Any]] = Field(..., max_length=1000, description="待脱敏记录列表")
    name_mode: str = Field("id", max_length=10, description="匿名模式: id/mask")


# ── Desensitize (v0.6) ──

# Anonymize a list of records.
@app.post("/api/desensitize/anonymize")
async def desensitize_anonymize(
    req: DesensitizeAnonRequest,
    _: str = Depends(require_api_key),
    _r: None = Depends(_require_ready),
):
    logger.info("desensitize/anonymize: %d records, mode=%s", len(req.records), req.name_mode)
    cfg = DesensitizeConfig(name_mode=req.name_mode, id_prefix=req.id_prefix)
    anon = DataAnonymizer(cfg)
    result = anon.anonymize_records(req.records)
    desensitized = anon.export_desensitized(req.records)
    return {
        "result": result.to_dict(),
        "desensitized_records": desensitized,
    }


# Export anonymized data.
@app.post("/api/desensitize/export")
async def desensitize_export(
    req: DesensitizeExportRequest,
    _: str = Depends(require_api_key),
    _r: None = Depends(_require_ready),
):
    logger.info("desensitize/export: %d records, mode=%s", len(req.records), req.name_mode)
    cfg = DesensitizeConfig(name_mode=req.name_mode)
    anon = DataAnonymizer(cfg)
    # SEC-19: after one-way export the reverse-anonymization map is cleared; name_count counts unique anonymized names from the results
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
# Subject course platform (PRD math-doubao, platform-content decoupling)
# Routes are subject-agnostic: the subject parameter selects a subject module via SubjectRegistry.
# Adding a subject (physics/chemistry/...) requires zero changes here — just register it under course/subjects/.
# ============================================================================


# List registered subjects and their capability manifests.
@app.get("/api/course/subjects")
async def course_subjects(_: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    if subject_registry is None:
        raise HTTPException(503, "subject registry not ready")
    return {"subjects": subject_registry.manifests()}


# Subject knowledge-graph node list (filter by stage/strand/grade/node_type).
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
    mod = _get_subject_module(subject)
    kg = mod.knowledge_graph()
    if kg is None:
        raise HTTPException(501, f"subject {subject} does not implement a knowledge graph")
    nodes = kg.query(stage=stage, strand=strand, grade=grade, node_type=node_type)
    return {"subject": subject, "count": len(nodes), "nodes": [n.to_dict() for n in nodes[:200]]}


# Subject knowledge-graph node detail (formula / common mistakes / related problem types / prerequisite chain).
@app.get("/api/course/{subject}/graph/node/{node_id}")
async def course_graph_node(
    subject: str,
    node_id: str,
    _: str = Depends(require_api_key),
    _r: None = Depends(_require_ready),
):
    mod = _get_subject_module(subject)
    kg = mod.knowledge_graph()
    if kg is None:
        raise HTTPException(501, f"subject {subject} does not implement a knowledge graph")
    node = kg.get_node(node_id)
    if node is None:
        raise HTTPException(404, f"node not found: {node_id}")
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


# Generate a subject Socratic lesson-script DSL following 5E (UC-M1).
#
#     issue #19 P0: returns a spec DSL v3.0 compliant structure (fusion-core SOCRATIC_DSL_V3_SCHEMA)
#     for downstream artifacts-engine/trainer/bench consumption. to_dict() preserves the internal teaching-script format.
@app.post("/api/course/{subject}/lesson-script")
async def course_lesson_script(
    subject: str,
    req: CourseLessonScriptRequest,
    _: str = Depends(require_api_key),
    _r: None = Depends(_require_ready),
):
    mod = _get_subject_module(subject)
    tutor = mod.socratic_tutor()
    if tutor is None:
        raise HTTPException(501, f"subject {subject} does not implement a socratic lesson script")
    dsl = await tutor.generate_lesson_script(
        topic=req.topic, grade=req.grade, knowledge_node_id=req.knowledge_node_id,
        prerequisites=req.prerequisites or None, misconceptions=req.misconceptions or None,
        layer=req.layer,
    )
    return dsl.to_spec_dict()


class CourseCheckpointRequest(BaseModel):
    checkpoint: dict
    student_answer: str


# Checkpoint judging — the subject verifier is the numeric authority (UC-M2).
@app.post("/api/course/{subject}/checkpoint")
async def course_checkpoint(
    subject: str,
    req: CourseCheckpointRequest,
    _: str = Depends(require_api_key),
    _r: None = Depends(_require_ready),
):
    from .course.models import Checkpoint
    mod = _get_subject_module(subject)
    tutor = mod.socratic_tutor()
    verifier = mod.verifier()
    if tutor is None and verifier is None:
        raise HTTPException(501, f"subject {subject} does not implement checkpoint judging")
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


# Problem to parameterized scene DSL (SymPy numeric overwrite, UC-M2 animation rendering).
@app.post("/api/course/{subject}/scene-compile")
async def course_scene_compile(
    subject: str,
    req: CourseSceneCompileRequest,
    _: str = Depends(require_api_key),
    _r: None = Depends(_require_ready),
):
    mod = _get_subject_module(subject)
    compiler = mod.scene_compiler()
    if compiler is None:
        raise HTTPException(501, f"subject {subject} does not implement scene compilation")
    dsl = await compiler.compile(req.problem_text, req.knowledge_node_id)
    return dsl.to_dict()


class CourseErrorAttributionRequest(BaseModel):
    node_id: str
    max_depth: int = 3


# Wrong-answer GraphRAG reverse attribution — trace the faulty path along prerequisite dependencies (UC-M4).
@app.post("/api/course/{subject}/error-attribution")
async def course_error_attribution(
    subject: str,
    req: CourseErrorAttributionRequest,
    _: str = Depends(require_api_key),
    _r: None = Depends(_require_ready),
):
    mod = _get_subject_module(subject)
    kg = mod.knowledge_graph()
    if kg is None:
        raise HTTPException(501, f"subject {subject} does not implement a knowledge graph")
    chain = kg.reverse_attribution(req.node_id, max_depth=req.max_depth)
    node = kg.get_node(req.node_id)
    return {
        "subject": subject,
        "source_node": node.to_dict() if node else None,
        "attribution_path": chain,
        "path_nodes": [kg.get_node(n).to_dict() if kg.get_node(n) else {"id": n} for n in chain],
    }


# Student subject-mastery heatmap (confidence heuristic, DKT alternative, UC-M3).
@app.get("/api/course/{subject}/mastery/{student_id}")
async def course_mastery(
    subject: str,
    student_id: str,
    _: str = Depends(require_api_key),
    _r: None = Depends(_require_ready),
):
    if subject_registry is None:
        raise HTTPException(503, "subject registry not ready")
    return {
        "subject": subject,
        "student_id": student_id,
        "profile": subject_registry.mastery.student_profile(student_id),
        "weak_nodes": subject_registry.mastery.weak_nodes(student_id),
    }


# Fetch the subject module from the registry; unregistered returns 404.
def _get_subject_module(subject: str):
    if subject_registry is None:
        raise HTTPException(503, "subject registry not ready")
    try:
        return subject_registry.get(subject)
    except Exception:
        raise HTTPException(404, f"subject not registered: {subject}")


# Subject problem-bank list (triplet tagging: knowledge point + cognitive level + error cause).
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
    mod = _get_subject_module(subject)
    bank = mod.problem_bank()
    if bank is None:
        raise HTTPException(404, f"subject {subject} does not implement a problem bank")
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


# Single problem detail (variables / expected answer / cognitive points).
@app.get("/api/course/{subject}/problem-bank/{problem_id}")
async def course_problem_detail(
    subject: str,
    problem_id: str,
    _: str = Depends(require_api_key),
    _r: None = Depends(_require_ready),
):
    mod = _get_subject_module(subject)
    bank = mod.problem_bank()
    if bank is None:
        raise HTTPException(404, f"subject {subject} does not implement a problem bank")
    p = bank.get(problem_id)
    if p is None:
        raise HTTPException(404, f"problem not found: {problem_id}")
    return {"subject": subject, "problem": p.to_dict()}


# ── Classroom module (classroom PRD E1-E6, K1 text mode) ──

# i18n: user-facing (OpenAPI field descriptions)
class ClassroomScriptRequest(BaseModel):
    subject: str = "数学"
    grade: str = "5"
    topic: str
    lesson_plan: dict = {}


# i18n: user-facing (OpenAPI field descriptions)
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
    # multiple_choice judging: the LLM-generated answer may be a letter ("A") while options are
    # full option texts — the frontend sends the option list, and the judge maps letters↔texts both ways.
    options: list[str] = Field(default_factory=list)


class ClassroomSessionRequest(BaseModel):
    code: str
    student_id: str = "guest"


# E1 teaching script generation — page-by-page narration + question points + emotion_tag.
@app.post("/api/classroom/script")
async def classroom_script(
    req: ClassroomScriptRequest,
    _: str = Depends(require_api_key),
    _r: None = Depends(_require_ready),
):
    if lesson_scripter is None:
        raise HTTPException(503, "classroom module not ready")
    script = await lesson_scripter.generate(
        subject=req.subject, grade=req.grade, topic=req.topic,
        lesson_plan=req.lesson_plan or None,
    )
    return script.to_dict()


# E2 course pack packaging — lesson plan + slides + quiz + script into a class_id + 6-digit classroom code.
@app.post("/api/classroom/pack")
async def classroom_pack(
    req: ClassroomPackRequest,
    _: str = Depends(require_api_key),
    _r: None = Depends(_require_ready),
):
    if packager is None:
        raise HTTPException(503, "classroom module not ready")
    pkg = packager.pack(
        subject=req.subject, grade=req.grade, topic=req.topic,
        lesson_plan=req.lesson_plan, slides=req.slides,
        quiz=req.quiz, script=req.script, material_flags=req.material_flags,
    )
    return pkg.to_dict()


# E3 student-side pack fetch — by classroom code or class_id.
@app.get("/api/classroom/pack/{code_or_id}")
async def classroom_get_pack(
    code_or_id: str,
    _: str = Depends(require_api_key),
    _r: None = Depends(_require_ready),
):
    if packager is None:
        raise HTTPException(503, "classroom module not ready")
    pkg = packager.get_by_code(code_or_id) or packager.get_by_id(code_or_id)
    if pkg is None:
        raise HTTPException(404, "invalid classroom code or pack deleted")
    return pkg.to_dict()


# Teacher-side course pack list.
@app.get("/api/classroom/packs")
async def classroom_list_packs(
    _: str = Depends(require_api_key),
    _r: None = Depends(_require_ready),
):
    if packager is None:
        raise HTTPException(503, "classroom module not ready")
    pkgs = packager.list_all()
    return {"count": len(pkgs), "packs": [p.to_manifest() for p in pkgs]}


# E5 create classroom session — K1 text mode only persists to the store (no LiveKit token).
@app.post("/api/classroom/session")
async def classroom_create_session(
    req: ClassroomSessionRequest,
    _: str = Depends(require_api_key),
    _r: None = Depends(_require_ready),
):
    if packager is None or session_manager is None:
        raise HTTPException(503, "classroom module not ready")
    pkg = packager.get_by_code(req.code)
    if pkg is None:
        raise HTTPException(404, "invalid classroom code or pack deleted")
    sess = session_manager.create_session(pkg.class_id, req.code, req.student_id)
    return {"session": sess.to_dict(), "package": pkg.to_dict()}


# E5 class dismissal — submit the classroom record.
@app.patch("/api/classroom/session/{session_id}/finish")
async def classroom_finish_session(
    session_id: str,
    abandoned: bool = False,
    _: str = Depends(require_api_key),
    _r: None = Depends(_require_ready),
):
    if session_manager is None:
        raise HTTPException(503, "classroom module not ready")
    sess = session_manager.finish_session(session_id, abandoned=abandoned)
    if sess is None:
        raise HTTPException(404, "session not found")
    return {"session": sess.to_dict()}


# E4 in-class answer judging — reuses AssessmentEngine / course checkpoint.
@app.post("/api/classroom/answer")
async def classroom_answer(
    req: ClassroomAnswerRequest,
    _: str = Depends(require_api_key),
    _r: None = Depends(_require_ready),
):
    if session_manager is None:
        raise HTTPException(503, "classroom module not ready")
    correct, feedback, detail = await _judge_classroom_answer(req)
    rec = session_manager.record_answer(
        req.session_id, req.question_id, req.student_answer,
        correct=correct, feedback=feedback, detail=detail,
    )
    return rec.to_dict()


# Judging dispatch: numeric/multiple_choice use local logic, open/expression delegate to AssessmentEngine.
async def _judge_classroom_answer(req: ClassroomAnswerRequest) -> tuple[bool, str, str]:
    qtype = req.question_type
    if qtype == "multiple_choice":
        expected = str(req.expected_answer).strip().upper()
        student = req.student_answer.strip()
        # Option mapping: when the answer is a letter ("A") but the student submitted option text (or vice versa), normalize both ways.
        # The LLM emits both forms: letter options (options=["A","B"]) or full-text options with a letter answer
        if req.options and len(student) != 1:
            letters = "ABCDEFGH"
            for i, opt in enumerate(req.options[: len(letters)]):
                if student == opt.strip():
                    student = letters[i]
                    break
        elif req.options and len(expected) == 1:
            # expected is a letter and student is a letter — already equal; the option-text case was normalized above
            pass
        correct = student.upper() == expected
        # i18n: user-facing (student feedback)
        return correct, "对!" if correct else f"应为 {req.expected_answer}", "multiple_choice"
    if qtype == "numeric":
        try:
            ok = abs(float(req.student_answer) - float(req.expected_answer)) <= 0.01 * max(1, abs(float(req.expected_answer)))
            # i18n: user-facing (student feedback)
            return ok, "数值正确" if ok else f"应为 {req.expected_answer}", "numeric"
        except (ValueError, TypeError):
            # i18n: user-facing (student feedback)
            return False, f"非数值, 应为 {req.expected_answer}", "numeric"
    # open / expression delegate to LLM judging
    if assessment_engine is not None:
        try:
            result = await assessment_engine.grade_math(
                problem=req.question_id, answer=req.student_answer,
                solution=req.expected_answer,
            )
            return bool(getattr(result, "correct", False)), getattr(result, "feedback", ""), "llm"
        except Exception as exc:
            logger.warning("classroom LLM judging failed: %s, falling back to string match", exc)
    # Fallback: string containment
    ok = req.expected_answer.strip() in req.student_answer if req.expected_answer else False
    # i18n: user-facing (student feedback)
    return ok, "参考答案匹配" if ok else "未匹配参考答案", "string_fallback"


# Record page-view progress (E5 pages_viewed).
@app.get("/api/classroom/session/{session_id}/page/{page_index}")
async def classroom_page_view(
    session_id: str,
    page_index: int,
    _: str = Depends(require_api_key),
    _r: None = Depends(_require_ready),
):
    if session_manager is None:
        raise HTTPException(503, "classroom module not ready")
    session_manager.record_page_view(session_id, page_index)
    return {"session_id": session_id, "page_index": page_index, "recorded": True}


# E6 classroom report — attendance/pages/quiz_stat/question_stat/weak_points.
@app.get("/api/classroom/report/{session_id}")
async def classroom_report(
    session_id: str,
    _: str = Depends(require_api_key),
    _r: None = Depends(_require_ready),
):
    if session_manager is None:
        raise HTTPException(503, "classroom module not ready")
    report = session_manager.build_report(session_id)
    return report.to_dict()


# Teacher-side session list for one course pack.
@app.get("/api/classroom/sessions/{class_id}")
async def classroom_list_sessions(
    class_id: str,
    _: str = Depends(require_api_key),
    _r: None = Depends(_require_ready),
):
    if session_manager is None:
        raise HTTPException(503, "classroom module not ready")
    sessions = session_manager.store.list_sessions(class_id)
    return {"class_id": class_id, "count": len(sessions), "sessions": sessions}


# WebSocket: Socratic lesson-script streaming generation (PRD §12.2, 5-event protocol)
# issue #20: two-stage CoT pipeline — enable_thinking streams reasoning into a structured DSL
# Stream lesson-script generation: start → stream_chunk(thinking) → stage_change → dsl_complete → finish/error.
#
#     issue #20: with FUSION_K12_COT_ENABLED=true the real two-stage path runs — thinking tokens are streamed;
#     otherwise a placeholder hint is sent (backward compatible).
@app.websocket("/ws/socratic-dsl")
async def ws_socratic_dsl(websocket: WebSocket):
    from ._prompt import build_prompt
    from .course.cot_pipeline import (
        COT_THINKING_PROMPT,
        cot_enabled,
        extract_thinking,
        stream_thinking,
    )

    await websocket.accept()
    try:
        payload = await websocket.receive_json()
        subject = str(payload.get("subject", "math"))
        topic = str(payload.get("topic", ""))
        grade = str(payload.get("grade", "5"))
        if not topic:
            await websocket.send_json({"event": "error", "data": {"message": "topic is required"}})
            await websocket.close()
            return
        await websocket.send_json({"event": "start", "data": {"stage": "thinking", "cot_enabled": cot_enabled()}})
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
            await websocket.send_json({"event": "error", "data": {"message": f"subject {subject} does not implement a lesson script"}})
            await websocket.close()
            return

        thinking_text = ""
        if cot_enabled() and mlx_client is not None:
            # Stage 1: real two-stage CoT — stream thinking tokens
            thinking_prompt = build_prompt(
                COT_THINKING_PROMPT,
                topic=topic, grade=grade,
                node_id=str(payload.get("knowledge_node_id", "")),
                prerequisites=str(payload.get("prerequisites") or ""),
                misconceptions=str(payload.get("misconceptions") or ""),
            )
            thinking_msgs = [{"role": "user", "content": thinking_prompt}]

            async def on_chunk(token: str) -> None:
                await websocket.send_json({"event": "stream_chunk", "data": {"stage": "thinking", "text": token}})

            thinking_text = await stream_thinking(
                mlx_client, thinking_msgs, on_chunk=on_chunk,
                temperature=0.5, max_tokens=2048,
            )
            thinking_text, _ = extract_thinking(thinking_text)
            logger.info("ws_socratic_dsl: CoT thinking %d chars", len(thinking_text))
        else:
            # Backward compatible: placeholder hint
            # i18n: user-facing (progress text streamed to the classroom UI)
            await websocket.send_json({"event": "stream_chunk", "data": {"stage": "thinking", "text": "正在分析知识点与教学路径..."}})

        await websocket.send_json({"event": "stage_change", "data": {"new_stage": "dsl"}})
        dsl = await tutor.generate_lesson_script(
            topic=topic, grade=grade,
            knowledge_node_id=str(payload.get("knowledge_node_id", "")) or None,
            prerequisites=payload.get("prerequisites") or None,
            misconceptions=payload.get("misconceptions") or None,
            layer=str(payload.get("layer", "B")) or "B",
        )
        # issue #19 P0: emit a spec DSL v3.0 compliant structure (fusion-core SOCRATIC_DSL_V3_SCHEMA)
        # to_dict() preserves the internal teaching-script format, to_spec_dict() converts to the spec contract for downstream consumers
        await websocket.send_json({"event": "dsl_complete", "data": {"dsl": dsl.to_spec_dict(), "thinking": thinking_text}})
        await websocket.send_json({"event": "finish", "data": {}})
    except Exception as exc:
        logger.warning("ws_socratic_dsl exception: %s", exc)
        try:
            await websocket.send_json({"event": "error", "data": {"message": str(exc)}})
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# ==================== Digital-human platform layer (K2/K3) ====================


# Create a digital-human session — load the script, prewarm plugins, return session_id + page manifest.
#
#     mode: topic=free topic (default) | course=teach by lesson plan (class_id required, reuses the classroom pack script_pages)
#         | expand=variation drills (class_id optional, graph context + extended narration) | qa=pure Q&A (ask directly)
@app.post("/api/digital-human/session")
async def dh_create_session(req: dict, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    if digital_human_manager is None:
        raise HTTPException(503, "digital_human_manager not initialized")
    subject = str(req.get("subject", "math"))
    topic = str(req.get("topic", ""))
    grade = str(req.get("grade", "3"))
    code = str(req.get("code", ""))
    student_id = str(req.get("student_id", ""))
    layer = str(req.get("layer", "B"))
    mode = str(req.get("mode", "topic"))
    class_id = str(req.get("class_id", ""))
    knowledge_node_id = str(req.get("knowledge_node_id", ""))
    lesson_plan = req.get("lesson_plan") or None
    # Reuse an existing script — if req carries script (pages), inject it into lesson_plan so the DH does not regenerate the narration
    script_pages = req.get("script", {}).get("pages") if isinstance(req.get("script"), dict) else None
    # course/expand modes: pull metadata from the classroom pack — course reuses script_pages directly (zero LLM);
    # expand takes only topic/subject/grade, narration goes through graph context + extended generation
    if mode in ("course", "expand") and class_id:
        try:
            pack = packager.get_by_id(class_id) or packager.get_by_code(class_id)
            script_obj = getattr(pack, "script", None) if pack is not None else None
            pages = script_obj.get("pages", []) if isinstance(script_obj, dict) else []
            if pages and mode == "course" and not script_pages:
                script_pages = pages
            # Both modes fill metadata from the pack (expand also needs topic)
            if pack is not None:
                topic = topic or str(getattr(pack, "topic", "") or "")
                subject = subject if req.get("subject") else str(getattr(pack, "subject", subject) or subject)
                grade = grade if req.get("grade") else str(getattr(pack, "grade", grade) or grade)
            if mode == "course" and not pages:
                logger.warning("dh course mode: classroom pack %s has no script pages (pages=%s)", class_id, len(pages))
        except Exception as exc:
            logger.warning("dh %s mode: classroom pack %s load failed, falling back to normal generation: %s", mode, class_id, exc)
    if script_pages and lesson_plan is None:
        lesson_plan = {}
    if script_pages:
        lesson_plan["script_pages"] = script_pages
    # mode=qa: pure Q&A — topic may be empty (question comes first)
    if not topic and mode != "qa":
        raise HTTPException(400, "topic is required")
    try:
        sess = await digital_human_manager.create_session(
            subject, topic, grade, code=code, student_id=student_id, layer=layer,
            lesson_plan=lesson_plan, mode=mode, knowledge_node_id=knowledge_node_id,
        )
    except Exception as exc:
        logger.error("dh_create_session failed: %s", exc, exc_info=True)
        raise HTTPException(500, str(exc))
    return {
        "session_id": sess.session_id, "page_count": sess.page_count,
        "pages": sess.page_manifest(), "subject": sess.subject, "topic": sess.topic,
        "mode": mode,
        "tts_available": sess.tts.available if sess.tts else False,
        "avatar_available": sess.avatar.available,
        "llm_available": sess.llm.available if sess.llm else False,
    }


# Sign a LiveKit token + room name. When livekit is unavailable a WS-only flag is returned.
@app.post("/api/digital-human/token")
async def dh_token(req: dict, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    if digital_human_manager is None:
        raise HTTPException(503, "digital_human_manager not initialized")
    session_id = str(req.get("session_id", ""))
    sess = digital_human_manager.get(session_id)
    if sess is None:
        raise HTTPException(404, "session not found")
    room = f"class_{sess.code or sess.session_id}"
    identity = f"student_{sess.student_id or session_id[-6:]}"
    token = ""
    lk_available = False
    try:
        token = sess.livekit.sign_token(identity, room)
        lk_available = True
    except Exception as exc:
        logger.info("dh_token: LiveKit unavailable, WS fallback: %s", exc)
    return {
        "session_id": session_id, "room": room, "identity": identity,
        "token": token, "livekit_available": lk_available,
        "livekit_url": sess.livekit.url,
    }


# Narrate a given page — TTS synthesis + Avatar rendering, returns audio/frame metadata (Phase B: audio over WS).
@app.post("/api/digital-human/narrate")
async def dh_narrate(req: dict, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    if digital_human_manager is None:
        raise HTTPException(503, "digital_human_manager not initialized")
    session_id = str(req.get("session_id", ""))
    idx = int(req.get("idx", 0))
    sess = digital_human_manager.get(session_id)
    if sess is None:
        raise HTTPException(404, "session not found")
    try:
        res = await sess.narrate_page(idx)
    except Exception as exc:
        logger.error("dh_narrate failed: %s", exc, exc_info=True)
        raise HTTPException(500, str(exc))
    return res


# Raise-hand question — LLM streaming answer (student text input, Phase D adds voice).
@app.post("/api/digital-human/raise-hand")
async def dh_raise_hand(req: dict, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    if digital_human_manager is None:
        raise HTTPException(503, "digital_human_manager not initialized")
    session_id = str(req.get("session_id", ""))
    text = str(req.get("text", ""))
    image_b64 = str(req.get("image_b64", "")).strip()
    sess = digital_human_manager.get(session_id)
    if sess is None:
        raise HTTPException(404, "session not found")
    if not text and not image_b64:
        raise HTTPException(400, "either text or image_b64 is required")
    try:
        res = await sess.raise_hand(text, image_b64=image_b64)
    except Exception as exc:
        logger.error("dh_raise_hand failed: %s", exc, exc_info=True)
        raise HTTPException(500, str(exc))
    return res


# End the digital-human session — release resources, persist the classroom record.
@app.post("/api/digital-human/finish")
async def dh_finish(req: dict, _: str = Depends(require_api_key), _r: None = Depends(_require_ready)):
    if digital_human_manager is None:
        raise HTTPException(503, "digital_human_manager not initialized")
    session_id = str(req.get("session_id", ""))
    try:
        res = await digital_human_manager.finish(session_id)
    except Exception as exc:
        logger.error("dh_finish failed: %s", exc, exc_info=True)
        raise HTTPException(500, str(exc))
    if res is None:
        raise HTTPException(404, "session not found")
    return res


# Digital-human WS — pushes status events/emotion/audio, receives student actions (narrate/raise_hand/finish).
#
#     Phase B: TTS audio over WS binary frames. Phase C: video over LiveKit.
@app.websocket("/ws/digital-human/{session_id}")
async def ws_digital_human(websocket: WebSocket, session_id: str):
    await websocket.accept()
    if digital_human_manager is None:
        await websocket.send_json({"event": "error", "data": {"message": "manager not initialized"}})
        await websocket.close()
        return
    sess = digital_human_manager.get(session_id)
    if sess is None:
        await websocket.send_json({"event": "error", "data": {"message": "session not found"}})
        await websocket.close()
        return
    logger.info("ws_digital_human[%s]: connected", session_id)
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
                    image_b64 = str(data.get("image_b64", "")).strip()
                    res = await sess.raise_hand(text, image_b64=image_b64)
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
                    await websocket.send_json({"event": "error", "data": {"message": f"unknown action: {action}"}})
            elif "bytes" in msg:
                pcm = msg["bytes"]
                await websocket.send_json({"event": "asr_start", "data": {}})
                res = await sess.on_student_speech(pcm)
                await websocket.send_json({"event": "qa_done", "data": res})
                if res.get("has_audio") and sess._last_audio:
                    await websocket.send_bytes(sess._last_audio)
    except WebSocketDisconnect:
        logger.info("ws_digital_human[%s]: disconnected", session_id)
    except Exception as exc:
        logger.warning("ws_digital_human[%s] exception: %s", session_id, exc)
        try:
            await websocket.send_json({"event": "error", "data": {"message": str(exc)}})
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# Teacher Web GUI static mount (PRD GUI §2: dist/ mounted at / by serve.py StaticFiles, API under /api/*)
_WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"
if _WEB_DIST.exists():
    app.mount("/", StaticFiles(directory=str(_WEB_DIST), html=True), name="web-gui")
    logger.info("web_gui: mounted dist/ %s", _WEB_DIST)
else:
    logger.debug("web_gui: dist/ missing, skipping static mount (use vite dev in development)")
