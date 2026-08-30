"""Repository 层 — v2.0 持久化解耦 (standalone SQLite / cluster Postgres)。"""

from .base import Repository
from .factory import get_repository
from .sqlite_repo import SQLiteRepository

__all__ = ["Repository", "SQLiteRepository", "get_repository"]
