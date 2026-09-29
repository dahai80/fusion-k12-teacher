"""Barge-in 事件总线 — TLive-Omni pattern 2。

统一管理所有插件 abort 与 Task 生命周期。单次广播, 不散落各插件中断代码。
fire(reason) 遍历注册插件 -> cancel_fn (abort asyncio task) + clear_fn (丢弃队列帧/PCM)。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

logger = logging.getLogger(__name__)


class BargeInBus:
    def __init__(self, session_id: str = "") -> None:
        self.session_id = session_id
        self._plugins: dict[str, dict[str, Any]] = {}
        self._tasks: set[asyncio.Task[Any]] = set()
        self._lock = asyncio.Lock()

    def register(
        self, name: str,
        cancel_fn: Callable[[], Coroutine[Any, Any, None] | None] | Callable[[], None],
        clear_fn: Callable[[], None] | None = None,
    ) -> None:
        self._plugins[name] = {"cancel": cancel_fn, "clear": clear_fn}
        logger.debug("barge_in[%s]: 注册插件 %s", self.session_id, name)

    def unregister(self, name: str) -> None:
        self._plugins.pop(name, None)

    def track(self, task: asyncio.Task[Any]) -> None:
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def fire(self, reason: str = "") -> None:
        async with self._lock:
            logger.info("barge_in[%s]: fire reason=%s plugins=%d", self.session_id, reason, len(self._plugins))
            for name, entry in list(self._plugins.items()):
                try:
                    res = entry["cancel"]()
                    if asyncio.iscoroutine(res):
                        await res
                except Exception as exc:
                    logger.error("barge_in[%s]: 插件 %s cancel 异常: %s", self.session_id, name, exc)
                if entry.get("clear") is not None:
                    try:
                        entry["clear"]()
                    except Exception as exc:
                        logger.error("barge_in[%s]: 插件 %s clear 异常: %s", self.session_id, name, exc)
            for task in list(self._tasks):
                if not task.done():
                    task.cancel()
            self._tasks.clear()

    def clear(self) -> None:
        self._plugins.clear()
        self._tasks.clear()
