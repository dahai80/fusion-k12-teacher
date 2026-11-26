# Cache backend abstract base class — M2-T12.
#
# Unified interface: get/set/delete/incr/expire.
# Rate-limit counters use incr (atomic increment), sessions use get/set+ttl,
# salt uses get/set.

from __future__ import annotations

from abc import ABC, abstractmethod


# Cache/counter backend abstraction. Implementations own serialization/atomicity/TTL.
class CacheBackend(ABC):

    # Read value — return None when missing.
    @abstractmethod
    async def get(self, key: str) -> str | None:
        pass

    # Write value — ttl>0 expires after ttl seconds, ttl=0 persists forever.
    @abstractmethod
    async def set(self, key: str, value: str, ttl: int = 0) -> None:
        pass

    # Delete key — no error when missing.
    @abstractmethod
    async def delete(self, key: str) -> None:
        pass

    # Atomic increment — returns the post-increment value. Sets ttl on first
    #         key creation; does not reset ttl when the key already exists.
    @abstractmethod
    async def incr(self, key: str, ttl: int = 60) -> int:
        pass

    # Set expiry on an existing key — no error when missing.
    @abstractmethod
    async def expire(self, key: str, ttl: int) -> None:
        pass

    # Release backend resources. No-op by default.
    async def aclose(self) -> None:
        pass
