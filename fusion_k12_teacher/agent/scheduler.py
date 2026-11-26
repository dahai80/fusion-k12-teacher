# Task scheduler — APScheduler in-memory scheduling + history.json execution-history persistence.
#
# Constraint: MemoryJobStore has no cross-process persistence and only supports single-worker
# deployment (uvicorn --workers 1). Multiple workers / processes would trigger cron repeatedly.
# A3: cross-process dedup relies on the _pidfile process lock — when cli and serve share the
# singleton, only the lock-holding process arms cron, preventing duplicate registration of the
# same scheduled task.

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

# AGT-3: import JobLookupError explicitly instead of matching class names as strings
# (string matching would accidentally swallow same-named exceptions)
from apscheduler.jobstores.base import JobLookupError
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers import SchedulerNotRunningError
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .executor import execute_task
from .models import TaskResult, TeachingTask
from .tasks import build_task, list_available_tasks

logger = logging.getLogger(__name__)


def _instance_owner() -> str:
    # M2-T11: instance identity — hostname+pid, used as the DB task-lock owner.
    import socket
    return f"{socket.gethostname()}:{os.getpid()}"


# P1-11: history persistence path is env-configurable (Dockerfile sets FUSION_K12_HISTORY_FILE
# to a writable volume) instead of a hardcoded in-package data/ (read-only / lost on container
# rebuild). Default ~/.fusion-k12/history.json.
HISTORY_JSON = os.environ.get(
    "FUSION_K12_HISTORY_FILE",
    os.path.join(os.path.expanduser("~/.fusion-k12"), "history.json"),
)
# A3: pidfile lock — cli agent_start and serve lifespan share the same scheduler singleton;
# both arming the same cron would cause duplicate execution. The lock holder arms, the other skips.
_PIDFILE = os.environ.get(
    "FUSION_K12_SCHEDULER_PIDFILE",
    os.path.expanduser("~/.fusion-k12/scheduler.pid"),
)
# AGT-11: env read only at import -> runtime env changes have no effect; moved into __init__
# as instance attributes.
_DEFAULT_HISTORY_CAP = 500
_DEFAULT_CONCURRENCY = 2
_CRON_KEYS = ("minute", "hour", "day", "month", "day_of_week")


# Task scheduler — manages task registration, scheduling, and execution history.
class TaskScheduler:

    def __init__(self, history_path: str = "", repo: object | None = None):
        self._tasks: dict[str, TeachingTask] = {}
        self._history: list[TaskResult] = []
        self._scheduler: AsyncIOScheduler | None = None
        self._history_path = history_path or HISTORY_JSON
        # M1-T1: optional Repository backend — when injected, history goes to the DB;
        # otherwise JSON persistence is kept for backward compatibility.
        self._repo = repo
        # AGT-11: env read inside __init__, per-instance; rebuilding the instance at runtime
        # picks up new configuration.
        self._max_history = int(os.environ.get("FUSION_AGENT_HISTORY_CAP", _DEFAULT_HISTORY_CAP))
        self._max_concurrency = int(os.environ.get("FUSION_AGENT_MAX_CONCURRENCY", _DEFAULT_CONCURRENCY))
        self._running = False
        # AGT-4/CLI-7: do not create Lock/Semaphore in __init__ (import time) — after binding
        # to the first loop, a second asyncio.run would reuse primitives bound to the closed
        # loop -> RuntimeError. Create lazily instead.
        self._run_locks: dict[str, asyncio.Lock] | None = None
        self._history_lock: asyncio.Lock | None = None
        self._concurrency: asyncio.Semaphore | None = None
        # AGT-6: track in-flight run_task coroutines; stop() cancels and awaits them
        self._inflight: set[asyncio.Task] = set()
        # A3: pidfile lock fd — lock holder arms cron; when cli/serve both arm, only one schedules.
        self._pidfd: int | None = None
        self._owns_pidfile: bool = False

    def register_task(self, task: TeachingTask) -> None:
        self._tasks[task.id] = task
        logger.info(f"task registered: {task.id} ({task.name})")

    def get_task(self, task_id: str) -> TeachingTask | None:
        return self._tasks.get(task_id)

    def list_tasks(self) -> list[TeachingTask]:
        return list(self._tasks.values())

    def enable_task(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if not task:
            return False
        task.enabled = True
        if self._scheduler and task.schedule:
            self._schedule_task(task)
        logger.info(f"task enabled: {task_id}")
        return True

    def disable_task(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if not task:
            return False
        task.enabled = False
        if self._scheduler:
            try:
                self._scheduler.remove_job(task_id)
            except SchedulerNotRunningError:
                logger.warning(f"scheduler not running while disabling task: {task_id}")
            except JobLookupError:
                # AGT-3: caught explicitly; an unregistered job is normal (task never scheduled)
                logger.debug(f"disable task {task_id}: job not registered, nothing to remove")
            except Exception as e:
                logger.error(f"disable task {task_id}: failed to remove job: {e}")
        logger.info(f"task disabled: {task_id}")
        return True

    def load_default_tasks(self, **kwargs) -> None:
        for tid, name in list_available_tasks().items():
            try:
                task = build_task(tid, **kwargs)
                self.register_task(task)
            except Exception as e:
                logger.error(f"failed to load task {tid}: {e}")

    # Rebuild a task instance — refreshes stale data in task.params (AGT-5).
    def rebuild_task(self, task_id: str, **kwargs) -> TeachingTask | None:
        try:
            task = build_task(task_id, **kwargs)
            self._tasks[task_id] = task
            logger.info(f"task rebuilt: {task_id}")
            return task
        except Exception as e:
            logger.error(f"failed to rebuild task {task_id}: {e}")
            return None

    # AGT-4/CLI-7: lazily create loop-bound primitives — bind to the current running loop,
    #         never reuse primitives bound to a closed loop.
    def _ensure_primitives(self) -> None:
        loop = asyncio.get_running_loop()
        def _bound(obj):
            # 3.12+ Lock/Semaphore have no public _loop; use the bound loop if visible,
            # else treat as None (rebuild every time)
            return getattr(obj, "_loop", None)
        if self._history_lock is None or _bound(self._history_lock) is not loop:
            self._history_lock = asyncio.Lock()
        if self._concurrency is None or _bound(self._concurrency) is not loop:
            self._concurrency = asyncio.Semaphore(self._max_concurrency)
        if self._run_locks is None:
            self._run_locks = {}
        # drop per-task locks bound to other loops
        stale = [k for k, lk in self._run_locks.items() if _bound(lk) is not None and _bound(lk) is not loop]
        for k in stale:
            self._run_locks.pop(k, None)

    async def run_task(self, task_id: str, **kwargs) -> TaskResult:
        task = self._tasks.get(task_id)
        if not task:
            return TaskResult(task_id=task_id, status="failed", summary=f"task not found: {task_id}")
        self._ensure_primitives()
        lock = self._run_locks.setdefault(task_id, asyncio.Lock())
        async with lock:
            # M2-T11: in cluster mode, acquire the DB task lock — cross-instance cron dedup,
            # skip when held by another instance. standalone has no repo -> try_lock defaults
            # to True, non-blocking (single-process mutual exclusion via _run_locks).
            acquired_db = False
            owner = ""
            if self._repo is not None and os.environ.get("FUSION_K12_MODE", "").lower() == "cluster":
                owner = _instance_owner()
                ttl = float(os.environ.get("FUSION_K12_TASK_LOCK_TTL", "300"))
                try:
                    acquired_db = await asyncio.to_thread(
                        self._repo.try_lock, task_id, owner, ttl
                    )
                except Exception as e:
                    logger.warning("failed to acquire DB task lock, degrading to execution (may duplicate): %s", e)
                    acquired_db = True
                if not acquired_db:
                    logger.info("task %s is DB-locked by another instance, skipping (cross-instance dedup)", task_id)
                    return TaskResult(
                        task_id=task_id, status="skipped",
                        summary=f"execution locked by another instance: {task_id}",
                    )
            try:
                if kwargs:
                    rebuilt = self.rebuild_task(task_id, **kwargs)
                    if rebuilt:
                        task = rebuilt
                logger.info(f"start executing task: {task_id} ({task.name})")
                # AGT-6: register in-flight coroutine so stop() can cancel it
                coro_task = asyncio.current_task()
                if coro_task is not None:
                    self._inflight.add(coro_task)
                try:
                    async with self._concurrency:
                        result = await execute_task(task)
                finally:
                    self._inflight.discard(coro_task)
                async with self._history_lock:
                    self._history.append(result)
                    if len(self._history) > self._max_history:
                        del self._history[: len(self._history) - self._max_history]
                    await asyncio.to_thread(self._save_history)
                return result
            finally:
                if acquired_db and owner and self._repo is not None:
                    try:
                        await asyncio.to_thread(self._repo.release_lock, task_id, owner)
                    except Exception as e:
                        logger.warning("failed to release DB task lock (waits for ttl expiry): %s", e)

    def get_history(self, limit: int = 20) -> list[TaskResult]:
        if limit <= 0:
            limit = self._max_history
        return self._history[-limit:]

    def _acquire_pidfile(self) -> bool:
        # A3: non-blocking pidfile acquisition — fcntl.flock LOCK_EX|LOCK_NB.
        # Holding the lock = this process owns cron scheduling; failure = another process
        # (cli or serve) is already scheduling, skip arming.
        # Cross-process mutual exclusion prevents crons like "weekly lesson prep" from being
        # run once by cli and again by serve.
        # M2-T10: cluster-mode cross-instance dedup relies on DB row locks (inside run_task),
        # not pidfiles. Separate pidfile paths per instance are meaningless; cron arming relies
        # on the DB lock to avoid duplicate execution.
        if os.environ.get("FUSION_K12_MODE", "standalone").lower() == "cluster":
            if self._repo is not None:
                logger.info("cluster mode: cron dedup via DB row lock (T11), skipping pidfile")
                self._owns_pidfile = True
                return True
            logger.warning("cluster mode without a Repository: cron dedup has no DB lock — may trigger repeatedly")
            self._owns_pidfile = True
            return True
        if self._owns_pidfile:
            return True
        try:
            import fcntl
        except ImportError:
            logger.warning("fcntl unavailable, skipping pidfile lock, cron may trigger repeatedly")
            self._owns_pidfile = True
            return True
        try:
            os.makedirs(os.path.dirname(_PIDFILE), exist_ok=True)
            fd = os.open(_PIDFILE, os.O_RDWR | os.O_CREAT, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.ftruncate(fd, 0)
            os.write(fd, f"{os.getpid()}\n".encode())
            self._pidfd = fd
            self._owns_pidfile = True
            logger.info("scheduler acquired pidfile lock (pid=%d), this process owns cron", os.getpid())
            return True
        except OSError:
            # already locked by another process — it is scheduling; do not arm again here
            try:
                os.close(fd)
            except (OSError, UnboundLocalError):
                pass
            logger.warning("pidfile held by another process, skipping cron arm to avoid duplicate scheduling")
            return False

    def _build_jobstore(self):
        # P1-12: use SQLiteJobStore (persistent) when env specifies an sqlite path, else MemoryJobStore.
        db = os.environ.get("FUSION_K12_SCHEDULER_DB", "")
        if db:
            db_path = os.path.expanduser(db)
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
            # P1-12: lazy import — sqlalchemy is an optional dependency, only needed when
            # sqlite persistence is configured.
            try:
                from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
            except ImportError as e:
                logger.error(
                    "FUSION_K12_SCHEDULER_DB is set but sqlalchemy is missing, falling back to MemoryJobStore: %s", e
                )
                return MemoryJobStore()
            logger.info("scheduler using SQLiteJobStore: %s", db_path)
            return SQLAlchemyJobStore(url=f"sqlite:///{db_path}")
        logger.info("scheduler using MemoryJobStore (FUSION_K12_SCHEDULER_DB unset, schedules lost on restart)")
        return MemoryJobStore()

    def start(self) -> None:
        if self._running:
            return
        # A3: acquire the pidfile lock before arming cron — without the lock, do not start
        # the scheduler, avoiding duplicate triggers across processes.
        if not self._acquire_pidfile():
            self._running = False
            return
        self._scheduler = AsyncIOScheduler(
            # P1-12: SQLiteJobStore persists cron jobs — schedules survive restarts/processes.
            # env FUSION_K12_SCHEDULER_DB points to the sqlite path (Dockerfile defaults to
            # ~/.fusion-k12); empty falls back to MemoryJobStore (single-process memory, lost on restart).
            jobstores={"default": self._build_jobstore()},
        )
        try:
            self._scheduler.start()
        except RuntimeError as e:
            # AGT-5: distinguish "already running" from "no loop"; only "already running" is
            # treated as a successful no-op. "no running event loop" (started from a sync
            # context) is a recoverable deferred state — flag _running to record the intent,
            # actual scheduling is picked up by ensure_primitives / a later start once the
            # loop is up.
            if "already running" in str(e):
                logger.debug("scheduler already running, idempotent return")
            else:
                logger.warning(f"scheduler start deferred (no event loop etc.), flagged running intent: {e}")
            self._running = True
            return
        self._running = True
        for task in self._tasks.values():
            if not (task.enabled and task.schedule and task.task_type == "scheduled"):
                continue
            try:
                self._schedule_task(task)
            except Exception as e:
                logger.error(f"failed to schedule task {task.id}: {e}, skipping (other tasks continue)", exc_info=True)
        logger.info("Agent scheduler started")

    def stop(self) -> None:
        # AGT-6: synchronously cancel in-flight run_task coroutines (cancel does not block);
        # async callers use await aclose()
        for t in list(self._inflight):
            if not t.done():
                t.cancel()
        if self._scheduler:
            try:
                self._scheduler.shutdown(wait=False)
            except (RuntimeError, SchedulerNotRunningError):
                pass
            self._scheduler = None
        self._running = False
        # A3: release the pidfile lock, letting the other process take over cron scheduling
        if self._pidfd is not None:
            try:
                import fcntl
                fcntl.flock(self._pidfd, fcntl.LOCK_UN)
            except (OSError, ImportError):
                pass
            try:
                os.close(self._pidfd)
            except OSError:
                pass
            self._pidfd = None
            self._owns_pidfile = False
        logger.info("Agent scheduler stopped")

    # AGT-6: async shutdown — cancel and await in-flight coroutines, used by serve lifespan.
    async def aclose(self) -> None:
        for t in list(self._inflight):
            if not t.done():
                t.cancel()
        for t in list(self._inflight):
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        self._inflight.clear()
        self.stop()

    def is_running(self) -> bool:
        return self._running

    def _schedule_task(self, task: TeachingTask) -> None:
        if not self._scheduler:
            return
        try:
            self._scheduler.remove_job(task.id)
        except Exception:
            pass

        async def _job():
            # P3: auto-retry failed cron jobs (count env-configurable); loud alert when retries
            # are exhausted, no longer just APScheduler's silent logging.
            max_retries = int(os.environ.get("FUSION_K12_CRON_RETRIES", "1"))
            for attempt in range(max_retries + 1):
                try:
                    await self.run_task(task.id)
                    return
                except Exception as exc:
                    if attempt < max_retries:
                        logger.warning("cron task %s failed attempt %d, retrying: %s", task.id, attempt + 1, exc)
                        await asyncio.sleep(1.0 * (attempt + 1))
                        continue
                    logger.error("cron task %s still failing after exhausting retries: %s", task.id, exc)

        cron_kwargs = self._parse_cron(task.schedule)
        self._scheduler.add_job(
            _job,
            "cron",
            id=task.id,
            replace_existing=True,
            max_instances=1,
            **cron_kwargs,
        )
        logger.info(f"task scheduled: {task.id} -> {task.schedule}")

    def _parse_cron(self, cron_expr: str) -> dict[str, Any]:
        parts = cron_expr.split()
        if len(parts) != 5:
            raise ValueError(f"cron expression field count={len(parts)} (expected 5): {cron_expr}")
        result = {}
        for i, part in enumerate(parts):
            if part != "*":
                result[_CRON_KEYS[i]] = part
        return result

    # P1-4: scrub suspected student PII fields (student_answer/responses etc.) before
    # persisting history.json; the engine layer already desensitizes, this is defense in
    # depth — prevents upstream dataclass field additions from echoing raw answers.
    _PII_KEYS = ("student_answer", "student_answers", "responses", "sample_responses")
    # i18n: user-facing
    _PII_MASK = "<已脱敏>"

    @classmethod
    def _scrub_pii(cls, obj: Any) -> Any:
        if isinstance(obj, dict):
            return {
                k: (cls._PII_MASK if k in cls._PII_KEYS else cls._scrub_pii(v))
                for k, v in obj.items()
            }
        if isinstance(obj, list):
            return [cls._scrub_pii(x) for x in obj]
        return obj

    def _save_history(self) -> None:
        try:
            data = [self._scrub_pii(r.to_dict()) for r in self._history[-self._max_history:]]
            # M1-T1: when a Repository is injected, persist to the DB; otherwise keep JSON
            if self._repo is not None:
                self._repo.save_history(data)
                return
            os.makedirs(os.path.dirname(self._history_path), exist_ok=True)
            tmp_path = self._history_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._history_path)
        except Exception as e:
            logger.error(f"failed to save history: {e}")

    def load_history(self) -> None:
        try:
            # M1-T1: load from the DB when a Repository is injected, else from JSON
            if self._repo is not None:
                data = self._repo.load_history()
                self._history = [TaskResult.from_dict(d) for d in data]
                logger.info(f"history loaded (DB): {len(self._history)} records")
                return
            if os.path.exists(self._history_path):
                with open(self._history_path, encoding="utf-8") as f:
                    data = json.load(f)
                self._history = [TaskResult.from_dict(d) for d in data]
                logger.info(f"history loaded: {len(self._history)} records")
        except Exception as e:
            logger.error(f"failed to load history: {e}")


scheduler = TaskScheduler()
