"""Redis cache backend — cluster mode (M2-T12).

redis-py is an optional dependency, imported lazily — raises ImportError when
missing (the factory falls back to LocalCache).
Uses the redis.asyncio client, fully async API.
Shared across instances: rate-limit counters (INCR+EXPIRE), sessions (SETEX),
salt (GET/SET).
"""

from __future__ import annotations

import logging

from .base import CacheBackend

logger = logging.getLogger(__name__)


class RedisCache(CacheBackend):
    """Async Redis backend — redis.asyncio connection."""

    def __init__(self, url: str):
        try:
            import redis.asyncio as aioredis
        except ImportError as e:
            raise ImportError(
                "cluster mode requires redis: pip install -e '.[cluster]'"
            ) from e
        self._client = aioredis.from_url(
            url, decode_responses=True, socket_timeout=5, socket_connect_timeout=5
        )
        logger.info("RedisCache configured and ready")

    async def get(self, key: str) -> str | None:
        return await self._client.get(key)

    async def set(self, key: str, value: str, ttl: int = 0) -> None:
        if ttl > 0:
            await self._client.set(key, value, ex=ttl)
        else:
            await self._client.set(key, value)

    async def delete(self, key: str) -> None:
        await self._client.delete(key)

    async def incr(self, key: str, ttl: int = 60) -> int:
        pipe = self._client.pipeline()
        pipe.incr(key)
        pipe.expire(key, ttl, nx=True)
        results = await pipe.execute()
        return int(results[0])

    async def expire(self, key: str, ttl: int) -> None:
        await self._client.expire(key, ttl)

    async def aclose(self) -> None:
        try:
            await self._client.aclose()
            logger.info("RedisCache connection closed")
        except Exception as e:
            logger.warning("Failed to close RedisCache: %s", e)
