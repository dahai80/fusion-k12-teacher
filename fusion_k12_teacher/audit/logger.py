"""审计日志器 — M3-T13/T14。

内存缓冲 + 批量落 Repository.audit_events (T14)。无 repo 时仅内存 (cap)。
后台异步 flush, 不阻塞请求。get_audit_logger() 单例。
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from .event import AuditEvent

logger = logging.getLogger(__name__)

_AUDIT: AuditLogger | None = None
_DEFAULT_CAP = 5000
_DEFAULT_FLUSH_BATCH = 50


class AuditLogger:
    """审计事件收集器 — 内存缓冲 + 批量持久化。"""

    def __init__(self, repo: object | None = None, cap: int = _DEFAULT_CAP):
        self._repo = repo
        self._cap = cap
        self._events: list[AuditEvent] = []
        self._lock = asyncio.Lock()
        self._flush_batch = int(os.environ.get("FUSION_K12_AUDIT_FLUSH_BATCH", _DEFAULT_FLUSH_BATCH))

    def set_repo(self, repo: object | None) -> None:
        """运行期切换后端 (cluster 模式 repo 惰性建后注入)。"""
        self._repo = repo

    async def record(self, event: AuditEvent) -> None:
        """记一条审计事件 — 入缓冲, 超 batch 则 flush。"""
        async with self._lock:
            self._events.append(event)
            if len(self._events) > self._cap:
                del self._events[: len(self._events) - self._cap]
            need_flush = len(self._events) >= self._flush_batch
        if need_flush:
            await self.flush()

    async def flush(self) -> int:
        """刷缓冲至 Repository — 返写入条数。无 repo 返 0, 不清缓冲 (保留供 recent)。"""
        if self._repo is None:
            return 0
        async with self._lock:
            if not self._events:
                return 0
            batch = self._events[: self._flush_batch]
            self._events = self._events[self._flush_batch:]
        try:
            rows = [e.to_dict() for e in batch]
            await asyncio.to_thread(self._repo.save_audit, rows)
            return len(rows)
        except Exception as e:
            logger.warning("审计 flush 失败, 回填缓冲: %s", e)
            async with self._lock:
                self._events = batch + self._events
            return 0

    async def aclose(self) -> None:
        """关闭 — flush 剩余事件。"""
        try:
            while True:
                n = await self.flush()
                if n == 0:
                    break
        except Exception as e:
            logger.warning("审计关闭 flush 失败: %s", e)

    def recent(self, limit: int = 100) -> list[dict[str, Any]]:
        """取最近 N 条内存事件 (导出/调试用)。"""
        return [e.to_dict() for e in self._events[-limit:]]


def get_audit_logger() -> AuditLogger:
    """单例审计日志器。"""
    global _AUDIT
    if _AUDIT is None:
        _AUDIT = AuditLogger()
    return _AUDIT
