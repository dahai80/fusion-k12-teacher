"""Repository 工厂 — 按 FUSION_K12_MODE 选后端。

standalone (默认): SQLiteRepository
cluster: PostgresRepository (asyncpg, M1-T2) — DSN 未配或 asyncpg 缺失
          抛 NonDegradableError 拒启 (issue #36 fail-closed, 不回退 SQLite)
"""

from __future__ import annotations

import logging
import os

from ..errors import NonDegradableError
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
                DSN 未配或 asyncpg 缺失抛 NonDegradableError 拒启 —
                静默回退 SQLite 会让多实例各自积累分裂数据 (split-brain),
                服务却报 Healthy, 监控/运维无信号 (issue #36 fail-closed)。
    """
    mode = os.environ.get("FUSION_K12_MODE", "standalone").lower()

    if mode == "cluster":
        dsn = os.environ.get("FUSION_K12_PG_DSN", "")
        if not dsn:
            logger.error(
                "FUSION_K12_MODE=cluster 但 FUSION_K12_PG_DSN 未配 — 拒绝启动, "
                "不回退 SQLite (多实例 split-brain 风险)"
            )
            raise NonDegradableError(
                "FUSION_K12_MODE=cluster 需要 FUSION_K12_PG_DSN (Postgres 连接串); "
                "未配置, 拒绝回退 SQLite (fail-closed)"
            )
        try:
            from .postgres_repo import PostgresRepository
            return PostgresRepository(dsn)
        except ImportError as e:
            logger.error(
                "FUSION_K12_MODE=cluster 但 asyncpg 缺失 (%s) — 拒绝启动, "
                "不回退 SQLite; 安装: pip install -e '.[cluster]'", e
            )
            raise NonDegradableError(
                "cluster 模式缺 asyncpg 依赖 — 安装: pip install -e '.[cluster]'; "
                "拒绝回退 SQLite (fail-closed)"
            ) from e

    logger.info("Repository 后端: SQLite (mode=%s, db=%s)", mode, _default_sqlite_path())
    return SQLiteRepository(_default_sqlite_path())
