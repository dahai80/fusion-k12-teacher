"""任务调度器 — APScheduler 内存调度 + history.json 执行历史持久化。

约束: MemoryJobStore 无跨进程持久化，仅支持单 worker 部署
(uvicorn --workers 1)。多 worker / 多进程会重复触发 cron；
A3: 跨进程去重靠 _pidfile 进程锁 — cli 与 serve 共用单例时,
仅持锁进程 arm cron, 防同一调度任务双重注册重复执行。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

# AGT-3: 显式 import JobLookupError, 不用字符串匹配类名 (会误吞同名异常)
from apscheduler.jobstores.base import JobLookupError
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers import SchedulerNotRunningError
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .executor import execute_task
from .models import TaskResult, TeachingTask
from .tasks import build_task, list_available_tasks

logger = logging.getLogger(__name__)

HISTORY_JSON = os.path.join(os.path.dirname(__file__), "data", "history.json")
# A3: pidfile 锁 — cli agent_start 与 serve lifespan 共用同一 scheduler 单例,
# 双臂触发同一 cron 会导致重复执行。持锁进程 arm, 未持锁进程跳过。
_PIDFILE = os.environ.get(
    "FUSION_K12_SCHEDULER_PIDFILE",
    os.path.expanduser("~/.fusion-k12/scheduler.pid"),
)
# AGT-11: env 仅 import 时读 → 运行期改 env 无效; 下移到 __init__ 实例属性。
_DEFAULT_HISTORY_CAP = 500
_DEFAULT_CONCURRENCY = 2
_CRON_KEYS = ("minute", "hour", "day", "month", "day_of_week")


class TaskScheduler:
    """任务调度器 — 管理任务注册、调度、执行历史。"""

    def __init__(self, history_path: str = ""):
        self._tasks: dict[str, TeachingTask] = {}
        self._history: list[TaskResult] = []
        self._scheduler: AsyncIOScheduler | None = None
        self._history_path = history_path or HISTORY_JSON
        # AGT-11: __init__ 内读 env, 每实例独立; 运行期重建实例即可生效新配置。
        self._max_history = int(os.environ.get("FUSION_AGENT_HISTORY_CAP", _DEFAULT_HISTORY_CAP))
        self._max_concurrency = int(os.environ.get("FUSION_AGENT_MAX_CONCURRENCY", _DEFAULT_CONCURRENCY))
        self._running = False
        # AGT-4/CLI-7: 不在 __init__(导入期)建 Lock/Semaphore, 绑定首个 loop 后
        # 第二次 asyncio.run 会复用已关闭 loop 的原语 → RuntimeError。改惰性建。
        self._run_locks: dict[str, asyncio.Lock] | None = None
        self._history_lock: asyncio.Lock | None = None
        self._concurrency: asyncio.Semaphore | None = None
        # AGT-6: 跟踪在飞 run_task 协程, stop 时取消并 await
        self._inflight: set[asyncio.Task] = set()
        # A3: pidfile 锁 fd — 持锁进程 arm cron, cli/serve 双臂时仅一方调度。
        self._pidfd: int | None = None
        self._owns_pidfile: bool = False

    def register_task(self, task: TeachingTask) -> None:
        self._tasks[task.id] = task
        logger.info(f"任务注册: {task.id} ({task.name})")

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
        logger.info(f"任务启用: {task_id}")
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
                logger.warning(f"禁用任务时调度器未运行: {task_id}")
            except JobLookupError:
                # AGT-3: 显式捕获, 作业未注册属正常(任务从未调度)
                logger.debug(f"禁用任务 {task_id}: 作业未注册, 无需移除")
            except Exception as e:
                logger.error(f"禁用任务 {task_id} 移除作业失败: {e}")
        logger.info(f"任务禁用: {task_id}")
        return True

    def load_default_tasks(self, **kwargs) -> None:
        for tid, name in list_available_tasks().items():
            try:
                task = build_task(tid, **kwargs)
                self.register_task(task)
            except Exception as e:
                logger.error(f"加载任务失败 {tid}: {e}")

    def rebuild_task(self, task_id: str, **kwargs) -> TeachingTask | None:
        """重建任务实例 — 用于刷新 task.params 中的过期数据 (AGT-5)。"""
        try:
            task = build_task(task_id, **kwargs)
            self._tasks[task_id] = task
            logger.info(f"任务重建: {task_id}")
            return task
        except Exception as e:
            logger.error(f"任务重建失败 {task_id}: {e}")
            return None

    def _ensure_primitives(self) -> None:
        """AGT-4/CLI-7: 惰性创建 loop-bound 原语 — 绑定当前 running loop, 不复用已关闭 loop 的旧原语。"""
        loop = asyncio.get_running_loop()
        def _bound(obj):
            # 3.12+ Lock/Semaphore 无公开 _loop; 用 bound loop 若可见, 否则视 None(每次重建)
            return getattr(obj, "_loop", None)
        if self._history_lock is None or _bound(self._history_lock) is not loop:
            self._history_lock = asyncio.Lock()
        if self._concurrency is None or _bound(self._concurrency) is not loop:
            self._concurrency = asyncio.Semaphore(self._max_concurrency)
        if self._run_locks is None:
            self._run_locks = {}
        # 清掉绑定其它 loop 的 per-task 锁
        stale = [k for k, lk in self._run_locks.items() if _bound(lk) is not None and _bound(lk) is not loop]
        for k in stale:
            self._run_locks.pop(k, None)

    async def run_task(self, task_id: str, **kwargs) -> TaskResult:
        task = self._tasks.get(task_id)
        if not task:
            return TaskResult(task_id=task_id, status="failed", summary=f"任务不存在: {task_id}")
        self._ensure_primitives()
        lock = self._run_locks.setdefault(task_id, asyncio.Lock())
        async with lock:
            if kwargs:
                rebuilt = self.rebuild_task(task_id, **kwargs)
                if rebuilt:
                    task = rebuilt
            logger.info(f"开始执行任务: {task_id} ({task.name})")
            # AGT-6: 记录在飞协程, stop() 可取消
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

    def get_history(self, limit: int = 20) -> list[TaskResult]:
        if limit <= 0:
            limit = self._max_history
        return self._history[-limit:]

    def _acquire_pidfile(self) -> bool:
        # A3: 非阻塞抢占 pidfile — fcntl.flock LOCK_EX|LOCK_NB。
        # 成功持锁 = 本进程负责 cron 调度; 失败 = 另一进程(cli 或 serve)已在调度, 跳过 arm。
        # 跨进程互斥, 防"每周备课"等 cron 被 cli+serve 各跑一遍。
        if self._owns_pidfile:
            return True
        try:
            import fcntl
        except ImportError:
            logger.warning("fcntl 不可用, 跳过 pidfile 锁, cron 可能重复触发")
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
            logger.info("调度器获取 pidfile 锁 (pid=%d), 本进程负责 cron", os.getpid())
            return True
        except OSError:
            # 已被其它进程持锁 — 另一进程正在调度, 本进程不重复 arm
            try:
                os.close(fd)
            except (OSError, UnboundLocalError):
                pass
            logger.warning("pidfile 已被其它进程持有, 本进程跳过 cron arm, 避免重复调度")
            return False

    def start(self) -> None:
        if self._running:
            return
        # A3: arm cron 前先抢 pidfile 锁 — 未持锁则不启动调度器, 避免多进程重复触发。
        if not self._acquire_pidfile():
            self._running = False
            return
        self._scheduler = AsyncIOScheduler(
            jobstores={"default": MemoryJobStore()},
        )
        try:
            self._scheduler.start()
        except RuntimeError as e:
            # AGT-5: 区分 "已运行" 与 "无 loop"; 仅 "已运行" 视为成功幂等。
            # "no running event loop"(同步上下文启动)是可恢复延迟态, 标 _running 表达
            # 启动意图, 实际调度等 loop 起来后由 ensure_primitives/重新 start 补。
            if "already running" in str(e):
                logger.debug("调度器已在运行, 幂等返回")
            else:
                logger.warning(f"调度器启动暂缓(无 event loop 等), 标记 running 意图: {e}")
            self._running = True
            return
        self._running = True
        for task in self._tasks.values():
            if not (task.enabled and task.schedule and task.task_type == "scheduled"):
                continue
            try:
                self._schedule_task(task)
            except Exception as e:
                logger.error(f"调度任务失败 {task.id}: {e}，跳过(其余任务继续)", exc_info=True)
        logger.info("Agent 调度器已启动")

    def stop(self) -> None:
        # AGT-6: 同步取消在飞 run_task 协程(cancel 不阻塞); 异步调用方用 await aclose()
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
        # A3: 释放 pidfile 锁, 允许另一进程接管 cron 调度
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
        logger.info("Agent 调度器已停止")

    async def aclose(self) -> None:
        """AGT-6: 异步关闭 — 取消并 await 在飞协程, 供 serve lifespan 用。"""
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
            await self.run_task(task.id)

        cron_kwargs = self._parse_cron(task.schedule)
        self._scheduler.add_job(
            _job,
            "cron",
            id=task.id,
            replace_existing=True,
            max_instances=1,
            **cron_kwargs,
        )
        logger.info(f"任务调度: {task.id} → {task.schedule}")

    def _parse_cron(self, cron_expr: str) -> dict[str, Any]:
        parts = cron_expr.split()
        if len(parts) != 5:
            raise ValueError(f"cron 表达式字段数={len(parts)} (应为5): {cron_expr}")
        result = {}
        for i, part in enumerate(parts):
            if part != "*":
                result[_CRON_KEYS[i]] = part
        return result

    def _save_history(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._history_path), exist_ok=True)
            data = [r.to_dict() for r in self._history[-self._max_history:]]
            tmp_path = self._history_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._history_path)
        except Exception as e:
            logger.error(f"保存历史失败: {e}")

    def load_history(self) -> None:
        try:
            if os.path.exists(self._history_path):
                with open(self._history_path, encoding="utf-8") as f:
                    data = json.load(f)
                self._history = [TaskResult.from_dict(d) for d in data]
                logger.info(f"加载历史: {len(self._history)} 条")
        except Exception as e:
            logger.error(f"加载历史失败: {e}")


scheduler = TaskScheduler()
