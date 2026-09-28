"""进程内缓存 — standalone 默认后端 (M2-T12)。

LRU + TTL, asyncio.Lock 保护。单进程正确; 多实例各自一份 (限流配额独立)。
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict

from .base import CacheBackend

# 惰性清扫最小间隔 (秒) — 防每次 incr 都全量扫描
_SWEEP_INTERVAL = 60.0


class LocalCache(CacheBackend):
    """进程内 OrderedDict LRU + TTL。"""

    def __init__(self, max_entries: int = 4096):
        self._data: OrderedDict[str, tuple[str, float]] = OrderedDict()
        self._max = max_entries
        self._lock = asyncio.Lock()
        self._counters: dict[str, int] = {}
        self._counter_ttl: dict[str, float] = {}
        self._last_sweep = 0.0

    def _expired(self, key: str, now: float) -> bool:
        val = self._data.get(key)
        if val is None:
            return True
        _, exp = val
        return exp > 0 and now >= exp

    async def get(self, key: str) -> str | None:
        now = time.monotonic()
        async with self._lock:
            if self._expired(key, now):
                self._data.pop(key, None)
                return None
            val = self._data.get(key)
            if val is None:
                return None
            self._data.move_to_end(key)
            return val[0]

    async def set(self, key: str, value: str, ttl: int = 0) -> None:
        now = time.monotonic()
        exp = now + ttl if ttl > 0 else 0.0
        async with self._lock:
            self._data[key] = (value, exp)
            self._data.move_to_end(key)
            while len(self._data) > self._max:
                self._data.popitem(last=False)

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._data.pop(key, None)
            self._counters.pop(key, None)
            self._counter_ttl.pop(key, None)

    async def incr(self, key: str, ttl: int = 60) -> int:
        now = time.monotonic()
        async with self._lock:
            # issue #15: 计数器 dict 无上限, 过期项仅在同 key 再 incr 时才清 —
            # 海量不同 key (如伪造 IP 限流) 可无限增长。惰性批量清扫兜底。
            if len(self._counters) > self._max and now - self._last_sweep >= _SWEEP_INTERVAL:
                self._sweep_expired(now)
            exp = self._counter_ttl.get(key, 0.0)
            if exp > 0 and now >= exp:
                self._counters.pop(key, None)
                self._counter_ttl.pop(key, None)
            if key not in self._counters:
                self._counters[key] = 1
                self._counter_ttl[key] = now + ttl
            else:
                self._counters[key] += 1
            return self._counters[key]

    def _sweep_expired(self, now: float) -> None:
        """批量清除过期计数器 — 须持 _lock 调用 (issue #15)。"""
        expired = [k for k, exp in self._counter_ttl.items() if exp > 0 and now >= exp]
        for k in expired:
            self._counters.pop(k, None)
            self._counter_ttl.pop(k, None)
        self._last_sweep = now

    async def expire(self, key: str, ttl: int) -> None:
        now = time.monotonic()
        async with self._lock:
            if key in self._data:
                val = self._data[key]
                self._data[key] = (val[0], now + ttl)
            if key in self._counters:
                self._counter_ttl[key] = now + ttl

    async def aclose(self) -> None:
        async with self._lock:
            self._data.clear()
            self._counters.clear()
            self._counter_ttl.clear()
