"""Repository 工厂 — 按 FUSION_K12_MODE 选后端。

standalone (默认): SQLiteRepository
cluster: PostgresRepository (M1-T2 接入)
"""

from __future__ import annotations

import logging
import os

from .base import Repository
from .sqlite_repo import SQLiteRepository

logger = logging.getLogger(__name__)


def get_repository() -> Repository:
    """按部署模式返回 Repository 单例。

    standalone: env FUSION_K12_REPO_DB 指定 sqlite 路径,
                默认 ~/.fusion-k12/k12.db
    cluster:    M1-T2 接入 PostgresRepository
    """
    mode = os.environ.get("FUSION_K12_MODE", "standalone").lower()

    if mode == "cluster":
        # M1-T2: PostgresRepository, 当前未实现, 回退 SQLite 并告警。
        logger.warning(
            "FUSION_K12_MODE=cluster 但 PostgresRepository 未实现 (M1-T2), "
            "临时回退 SQLite — 多实例不一致风险"
        )
        db_path = os.environ.get(
            "FUSION_K12_REPO_DB",
            os.path.join(os.path.expanduser("~/.fusion-k12"), "k12.db"),
        )
        return SQLiteRepository(db_path)

    db_path = os.environ.get(
        "FUSION_K12_REPO_DB",
        os.path.join(os.path.expanduser("~/.fusion-k12"), "k12.db"),
    )
    logger.info("Repository 后端: SQLite (mode=%s, db=%s)", mode, db_path)
    return SQLiteRepository(db_path)
