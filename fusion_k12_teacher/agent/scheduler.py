"""任务调度器 — APScheduler 内存调度 + history.json 执行历史持久化。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers import SchedulerNotRunningError
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .executor import execute_task
from .models import TaskResult, TeachingTask
from .tasks import build_task, list_available_tasks

logger = logging.getLogger(__name__)

HISTORY_JSON = os.path.join(os.path.dirname(__file__), "data", "history.json")


class TaskScheduler:
    """任务调度器 — 管理任务注册、调度、执行历史。"""

    def __init__(self, history_path: str = ""):
        self._tasks: dict[str, TeachingTask] = {}
        self._history: list[TaskResult] = []
        self._scheduler: AsyncIOScheduler | None = None
        self._history_path = history_path or HISTORY_JSON
        self._running = False
        self._run_locks: dict[str, asyncio.Lock] = {}
        self._history_lock = asyncio.Lock()

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
            except Exception:
                pass
        logger.info(f"任务禁用: {task_id}")
        return True

    def load_default_tasks(self, **kwargs) -> None:
        for tid, name in list_available_tasks().items():
            try:
                task = build_task(tid, **kwargs)
                self.register_task(task)
            except Exception as e:
                logger.error(f"加载任务失败 {tid}: {e}")

    async def run_task(self, task_id: str) -> TaskResult:
        task = self._tasks.get(task_id)
        if not task:
            return TaskResult(task_id=task_id, status="failed", summary=f"任务不存在: {task_id}")
        lock = self._run_locks.setdefault(task_id, asyncio.Lock())
        async with lock:
            logger.info(f"开始执行任务: {task_id} ({task.name})")
            result = await execute_task(task)
            async with self._history_lock:
                self._history.append(result)
                await asyncio.to_thread(self._save_history)
            return result

    def get_history(self, limit: int = 20) -> list[TaskResult]:
        return self._history[-limit:]

    def start(self) -> None:
        if self._running:
            return
        self._scheduler = AsyncIOScheduler(
            jobstores={"default": MemoryJobStore()},
        )
        try:
            self._scheduler.start()
        except RuntimeError:
            pass
        self._running = True
        for task in self._tasks.values():
            if task.enabled and task.schedule and task.task_type == "scheduled":
                self._schedule_task(task)
        logger.info("Agent 调度器已启动")

    def stop(self) -> None:
        if self._scheduler:
            try:
                self._scheduler.shutdown(wait=False)
            except (RuntimeError, SchedulerNotRunningError):
                pass
            self._scheduler = None
        self._running = False
        logger.info("Agent 调度器已停止")

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

        self._scheduler.add_job(
            _job,
            "cron",
            id=task.id,
            replace_existing=True,
            **self._parse_cron(task.schedule),
        )
        logger.info(f"任务调度: {task.id} → {task.schedule}")

    def _parse_cron(self, cron_expr: str) -> dict[str, Any]:
        parts = cron_expr.split()
        if len(parts) != 5:
            logger.warning("cron 表达式字段数=%d (应为5): %s", len(parts), cron_expr)
        keys = ["minute", "hour", "day", "month", "day_of_week"]
        result = {}
        for i, part in enumerate(parts):
            if i < len(keys) and part != "*":
                result[keys[i]] = part
        return result

    def _save_history(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._history_path), exist_ok=True)
            data = [r.to_dict() for r in self._history[-100:]]
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
