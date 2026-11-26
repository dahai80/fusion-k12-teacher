# Cache backends — v2.0 M2-T12.
#
# standalone: in-process LRU (LocalCache), zero dependencies.
# cluster: Redis (RedisCache) — shares rate-limit counters/sessions/salt across
# instances.
# The get_cache() factory selects the backend by FUSION_K12_MODE; falls back to
# LocalCache when redis is missing.

from __future__ import annotations

import logging
import os

from .base import CacheBackend
from .local import LocalCache

logger = logging.getLogger(__name__)

_cache: CacheBackend | None = None


# Singleton cache backend — builds the instance by mode on first call, reuses afterwards.
def get_cache() -> CacheBackend:
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
                logger.info("cluster mode: RedisCache ready (%s)", _url_redacted(url))
                return _cache
            except ImportError as e:
                logger.warning("redis not installed, rate-limit/cache fall back to in-process (single-instance correct): %s", e)
            except Exception as e:
                logger.warning("Redis connection failed, falling back to LocalCache: %s", e)
        else:
            logger.warning("cluster mode without FUSION_K12_REDIS_URL configured, falling back to LocalCache")
    _cache = LocalCache()
    logger.info("LocalCache ready (in-process)")
    return _cache


def _url_redacted(url: str) -> str:
    if "@" in url and "://" in url:
        scheme, rest = url.split("://", 1)
        head, tail = rest.rsplit("@", 1)
        user = head.split(":", 1)[0]
        return f"{scheme}://{user}:***@{tail}"
    return url


__all__ = ["CacheBackend", "LocalCache", "get_cache"]
