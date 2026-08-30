"""缓存后端抽象基类 — M2-T12。

统一接口: get/set/delete/incr/expire。
限流计数用 incr (原子自增), 会话用 get/set+ttl, salt 用 get/set。
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class CacheBackend(ABC):
    """缓存/计数后端抽象。实现负责序列化/原子性/TTL。"""

    @abstractmethod
    async def get(self, key: str) -> str | None:
        """取值 — 不存在返 None。"""

    @abstractmethod
    async def set(self, key: str, value: str, ttl: int = 0) -> None:
        """写值 — ttl>0 秒过期, ttl=0 永久。"""

    @abstractmethod
    async def delete(self, key: str) -> None:
        """删键 — 不存在不报错。"""

    @abstractmethod
    async def incr(self, key: str, ttl: int = 60) -> int:
        """原子自增 — 返自增后值。首次建键设 ttl, 已存在不重设 ttl。"""

    @abstractmethod
    async def expire(self, key: str, ttl: int) -> None:
        """给已存键设过期 — 不存在不报错。"""

    async def aclose(self) -> None:
        """释放后端资源。默认空。"""
