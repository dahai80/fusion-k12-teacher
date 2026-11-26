# Repository factory — selects the backend by FUSION_K12_MODE.
#
# standalone (default): SQLiteRepository
# cluster: PostgresRepository (asyncpg, M1-T2) — missing DSN or missing asyncpg
#           raises NonDegradableError and refuses startup (issue #36 fail-closed, no SQLite fallback)

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


# Return a Repository instance for the deployment mode.
#
#     standalone: SQLiteRepository, env FUSION_K12_REPO_DB (default ~/.fusion-k12/k12.db)
#     cluster:    PostgresRepository, env FUSION_K12_PG_DSN holds the connection string;
#                 missing DSN or missing asyncpg raises NonDegradableError and refuses startup —
#                 a silent SQLite fallback would let replicas accumulate divergent data
#                 (split-brain) while reporting Healthy, with no signal for monitoring/ops
#                 (issue #36 fail-closed).
def get_repository() -> Repository:
    mode = os.environ.get("FUSION_K12_MODE", "standalone").lower()

    if mode == "cluster":
        dsn = os.environ.get("FUSION_K12_PG_DSN", "")
        if not dsn:
            logger.error(
                "FUSION_K12_MODE=cluster but FUSION_K12_PG_DSN is not set — refusing to start, "
                "no SQLite fallback (multi-instance split-brain risk)"
            )
            raise NonDegradableError(
                "FUSION_K12_MODE=cluster requires FUSION_K12_PG_DSN (Postgres connection string); "
                "not configured, refusing to fall back to SQLite (fail-closed)"
            )
        try:
            from .postgres_repo import PostgresRepository
            return PostgresRepository(dsn)
        except ImportError as e:
            logger.error(
                "FUSION_K12_MODE=cluster but asyncpg is missing (%s) — refusing to start, "
                "no SQLite fallback; install: pip install -e '.[cluster]'", e
            )
            raise NonDegradableError(
                "cluster mode missing asyncpg dependency — install: pip install -e '.[cluster]'; "
                "refusing to fall back to SQLite (fail-closed)"
            ) from e

    logger.info("Repository backend: SQLite (mode=%s, db=%s)", mode, _default_sqlite_path())
    return SQLiteRepository(_default_sqlite_path())
