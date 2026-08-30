"""Redis 缓存后端 — cluster 模式 (M2-T12)。

redis-py 可选依赖, 惰性 import — 缺失抛 ImportError (工厂回退 LocalCache)。
用 redis.asyncio 客户端, 全异步 API。
跨实例共享: 限流计数 (INCR+EXPIRE)、会话 (SETEX)、salt (GET/SET)。
"""

from __future__ import annotations

import logging

from .base import CacheBackend

logger = logging.getLogger(__name__)


class RedisCache(CacheBackend):
    """异步 Redis 后端 — redis.asyncio 连接。"""

    def __init__(self, url: str):
        try:
            import redis.asyncio as aioredis
        except ImportError as e:
            raise ImportError(
                "cluster 模式需 redis: pip install -e '.[cluster]'"
            ) from e
        self._client = aioredis.from_url(
            url, decode_responses=True, socket_timeout=5, socket_connect_timeout=5
        )
        logger.info("RedisCache 配置就绪")

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
            logger.info("RedisCache 连接已关闭")
        except Exception as e:
            logger.warning("关闭 RedisCache 失败: %s", e)
