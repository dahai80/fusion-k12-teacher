"""Repository 工厂 — 按 FUSION_K12_MODE 选后端。

standalone (默认): SQLiteRepository
cluster: PostgresRepository (asyncpg, M1-T2) — 缺 asyncpg 则回退 SQLite + 告警
"""

from __future__ import annotations

import logging
import os

from .base import Repository
from .sqlite_repo import SQLiteRepository

logger = logging.getLogger(__name__)


def _default_sqlite_path() -> str:
    return os.environ.get(
        "FUSION_K12_REPO_DB",
        os.path.join(os.path.expanduser("~/.fusion-k12"), "k12.db"),
    )


def get_repository() -> Repository:
    """按部署模式返回 Repository 实例。

    standalone: SQLiteRepository, env FUSION_K12_REPO_DB (默认 ~/.fusion-k12/k12.db)
    cluster:    PostgresRepository, env FUSION_K12_PG_DSN 指定连接串;
                asyncpg 缺失或 DSN 未配则回退 SQLite + 告警 (多实例不一致风险)。
    """
    mode = os.environ.get("FUSION_K12_MODE", "standalone").lower()

    if mode == "cluster":
        dsn = os.environ.get("FUSION_K12_PG_DSN", "")
        if not dsn:
            logger.warning(
                "FUSION_K12_MODE=cluster 但 FUSION_K12_PG_DSN 未配, 回退 SQLite — 多实例不一致风险"
            )
            return SQLiteRepository(_default_sqlite_path())
        try:
            from .postgres_repo import PostgresRepository
            return PostgresRepository(dsn)
        except ImportError as e:
            logger.warning(
                "FUSION_K12_MODE=cluster 但 asyncpg 缺失 (%s), 回退 SQLite — "
                "安装: pip install -e '.[cluster]'", e
            )
            return SQLiteRepository(_default_sqlite_path())

    logger.info("Repository 后端: SQLite (mode=%s, db=%s)", mode, _default_sqlite_path())
    return SQLiteRepository(_default_sqlite_path())
