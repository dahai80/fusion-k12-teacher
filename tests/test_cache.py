"""M2-T12 缓存后端测试 — LocalCache 行为 + get_cache 工厂。"""

from __future__ import annotations

import os

import pytest

from fusion_k12_teacher.cache import LocalCache, get_cache
from fusion_k12_teacher.cache.local import LocalCache as LC


@pytest.mark.asyncio
async def test_local_cache_set_get():
    c = LC()
    await c.set("k", "v", ttl=10)
    assert await c.get("k") == "v"


@pytest.mark.asyncio
async def test_local_cache_missing():
    c = LC()
    assert await c.get("nope") is None


@pytest.mark.asyncio
async def test_local_cache_ttl_expire():
    c = LC()
    await c.set("k", "v")  # ttl=0 永久
    assert await c.get("k") == "v"
    await c.expire("k", ttl=10)
    assert await c.get("k") == "v"  # 续期后仍存在


@pytest.mark.asyncio
async def test_local_cache_ttl_actually_expires():
    c = LC()
    await c.set("k", "v", ttl=0)
    await c.expire("k", ttl=0)  # ttl=0 → 立即过期
    assert await c.get("k") is None


@pytest.mark.asyncio
async def test_local_cache_delete():
    c = LC()
    await c.set("k", "v")
    await c.delete("k")
    assert await c.get("k") is None


@pytest.mark.asyncio
async def test_local_cache_incr():
    c = LC()
    n1 = await c.incr("cnt", ttl=60)
    n2 = await c.incr("cnt", ttl=60)
    n3 = await c.incr("cnt", ttl=60)
    assert (n1, n2, n3) == (1, 2, 3)


@pytest.mark.asyncio
async def test_local_cache_incr_new_key_ttl():
    c = LC()
    await c.incr("c", ttl=60)
    assert "c" in c._counters
    assert c._counter_ttl["c"] > 0


@pytest.mark.asyncio
async def test_local_cache_lru_evict():
    c = LC(max_entries=2)
    await c.set("a", "1")
    await c.set("b", "2")
    await c.set("c", "3")  # 驱逐 a
    assert await c.get("a") is None
    assert await c.get("c") == "3"


@pytest.mark.asyncio
async def test_get_cache_singleton():
    c1 = get_cache()
    c2 = get_cache()
    assert c1 is c2


@pytest.mark.asyncio
async def test_get_cache_standalone_local():
    os.environ.pop("FUSION_K12_MODE", None)
    os.environ.pop("FUSION_K12_REDIS_URL", None)
    import fusion_k12_teacher.cache as mod
    mod._cache = None
    c = get_cache()
    assert isinstance(c, LocalCache)


@pytest.mark.asyncio
async def test_get_cache_cluster_no_redis_fallback():
    os.environ["FUSION_K12_MODE"] = "cluster"
    os.environ.pop("FUSION_K12_REDIS_URL", None)
    import fusion_k12_teacher.cache as mod
    mod._cache = None
    c = get_cache()
    assert isinstance(c, LocalCache)
    os.environ.pop("FUSION_K12_MODE")
