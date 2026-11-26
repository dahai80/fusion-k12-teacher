# Audit logger — M3-T13/T14.
#
# In-memory buffer + batched writes to Repository.audit_events (T14). Without a repo, memory-only (capped).
# Background async flush, never blocks requests. get_audit_logger() singleton.

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


# Audit event collector — in-memory buffer + batched persistence.
class AuditLogger:

    def __init__(self, repo: object | None = None, cap: int = _DEFAULT_CAP):
        self._repo = repo
        self._cap = cap
        self._events: list[AuditEvent] = []
        self._lock = asyncio.Lock()
        self._flush_batch = int(os.environ.get("FUSION_K12_AUDIT_FLUSH_BATCH", _DEFAULT_FLUSH_BATCH))

    # Swap the backend at runtime (cluster mode injects the lazily-built repo).
    def set_repo(self, repo: object | None) -> None:
        self._repo = repo

    # Record one audit event — appended to the buffer, flushed once over batch size.
    async def record(self, event: AuditEvent) -> None:
        async with self._lock:
            self._events.append(event)
            if len(self._events) > self._cap:
                del self._events[: len(self._events) - self._cap]
            need_flush = len(self._events) >= self._flush_batch
        if need_flush:
            await self.flush()

    # Flush the buffer to the Repository — returns the number of rows written. Without a repo returns 0 and keeps the buffer (retained for recent).
    async def flush(self) -> int:
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
            logger.warning("audit flush failed, refilling buffer: %s", e)
            async with self._lock:
                self._events = batch + self._events
            return 0

    # Close — flush remaining events.
    async def aclose(self) -> None:
        try:
            while True:
                n = await self.flush()
                if n == 0:
                    break
        except Exception as e:
            logger.warning("audit close flush failed: %s", e)

    # Return the most recent N in-memory events (for export/debugging).
    def recent(self, limit: int = 100) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self._events[-limit:]]


# Singleton audit logger.
def get_audit_logger() -> AuditLogger:
    global _AUDIT
    if _AUDIT is None:
        _AUDIT = AuditLogger()
    return _AUDIT
