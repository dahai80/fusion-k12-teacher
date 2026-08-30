"""Repository 层 — v2.0 持久化解耦 (standalone SQLite / cluster Postgres)。"""

from .base import Repository
from .factory import get_repository
from .sqlite_repo import SQLiteRepository

__all__ = ["Repository", "SQLiteRepository", "get_repository"]


def __getattr__(name):
    # M1-T2: PostgresRepository 惰性导出 — 缺 asyncpg 不影响 import 包
    if name == "PostgresRepository":
        from .postgres_repo import PostgresRepository
        return PostgresRepository
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
