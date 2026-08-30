"""缓存后端 — v2.0 M2-T12。

standalone: 进程内 LRU (LocalCache), 零依赖。
cluster: Redis (RedisCache) — 跨实例共享限流计数/会话/salt。
get_cache() 工厂按 FUSION_K12_MODE 选后端, redis 缺失回退 LocalCache。
"""

from __future__ import annotations

import logging
import os

from .base import CacheBackend
from .local import LocalCache

logger = logging.getLogger(__name__)

_cache: CacheBackend | None = None


def get_cache() -> CacheBackend:
    """单例缓存后端 — 首次调按 mode 建实例, 后续复用。"""
    global _cache
    if _cache is not None:
        return _cache
    mode = os.environ.get("FUSION_K12_MODE", "standalone").lower()
    if mode == "cluster":
        url = os.environ.get("FUSION_K12_REDIS_URL", "")
        if url:
            try:
                from .redis_client import RedisCache
                _cache = RedisCache(url)
                logger.info("cluster 模式: RedisCache 就绪 (%s)", _url_redacted(url))
                return _cache
            except ImportError as e:
                logger.warning("redis 未装, 限流/缓存回退进程内 (单实例正确): %s", e)
            except Exception as e:
                logger.warning("Redis 连接失败, 回退 LocalCache: %s", e)
        else:
            logger.warning("cluster 模式未配 FUSION_K12_REDIS_URL, 回退 LocalCache")
    _cache = LocalCache()
    logger.info("LocalCache 就绪 (进程内)")
    return _cache


def _url_redacted(url: str) -> str:
    if "@" in url and "://" in url:
        scheme, rest = url.split("://", 1)
        head, tail = rest.rsplit("@", 1)
        user = head.split(":", 1)[0]
        return f"{scheme}://{user}:***@{tail}"
    return url


__all__ = ["CacheBackend", "LocalCache", "get_cache"]
