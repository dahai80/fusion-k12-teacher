"""Postgres Repository — cluster mode backend (M1-T2).

asyncpg is an optional dependency, lazily imported — if missing the factory raises
NonDegradableError and refuses to start (issue #36).
Schema aligned with SQLiteRepository (task_history / name_map).
Connection pool via asyncpg.create_pool, fully async API.

Note: this class is fully async; its interface is not in sync with SQLiteRepository (sync).
Callers (cluster-mode serve) must use the async API; standalone uses sync SQLite.
Therefore the Repository ABC keeps the sync interface, and Postgres provides async
adapter methods.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from .base import Repository

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS task_history (
    id      SERIAL PRIMARY KEY,
    ts      TEXT    NOT NULL,
    payload TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS name_map (
    map_key TEXT PRIMARY KEY,
    anon_id TEXT NOT NULL,
    reverse TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS task_lock (
    task_id     TEXT PRIMARY KEY,
    owner       TEXT NOT NULL,
    acquired_ts DOUBLE PRECISION NOT NULL,
    ttl         DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_events (
    id           SERIAL PRIMARY KEY,
    ts           TEXT    NOT NULL,
    trace_id     TEXT    NOT NULL DEFAULT '',
    route        TEXT    NOT NULL DEFAULT '',
    method       TEXT    NOT NULL DEFAULT '',
    status       INTEGER NOT NULL DEFAULT 0,
    duration_ms  DOUBLE PRECISION NOT NULL DEFAULT 0,
    student_hash TEXT    NOT NULL DEFAULT '',
    llm_model    TEXT    NOT NULL DEFAULT '',
    llm_status   TEXT    NOT NULL DEFAULT '',
    client_ip    TEXT    NOT NULL DEFAULT '',
    error        TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_events(ts);
"""

# M1-T6: encrypted columns — name_hash (sha256 query key) + name_encrypted (AES-GCM reversible).
_ADD_CRYPTO_COLS = [
    "ALTER TABLE name_map ADD COLUMN IF NOT EXISTS name_hash TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE name_map ADD COLUMN IF NOT EXISTS name_encrypted TEXT NOT NULL DEFAULT ''",
]


class PostgresRepository(Repository):
    """Cluster Postgres persistence backend — asyncpg connection pool.

    Constructor lazily imports asyncpg; raises ImportError when missing (factory converts
    to NonDegradableError and refuses to start, issue #36).
    The pool is created lazily in ensure_pool() (on first use), avoiding a construction-time
    DB connection failure blocking startup.
    """

    def __init__(self, dsn: str, min_size: int = 2, max_size: int = 10):
        try:
            import asyncpg  # noqa: F401
        except ImportError as e:
            raise ImportError(
                "cluster mode requires asyncpg: pip install -e '.[cluster]'"
            ) from e
        self._dsn = dsn
        self._min_size = min_size
        self._max_size = max_size
        self._pool = None
        logger.info("PostgresRepository configured (dsn=%s), pool created lazily", self._dsn_redacted())

    def _dsn_redacted(self) -> str:
        # Log redaction: hide password
        if "@" in self._dsn:
            scheme_part, rest = self._dsn.split("://", 1) if "://" in self._dsn else ("", self._dsn)
            head, tail = rest.rsplit("@", 1)
            if ":" in head:
                user = head.split(":", 1)[0]
                redacted = f"{scheme_part}://{user}:***@{tail}" if scheme_part else f"{user}:***@{tail}"
                return redacted
        return self._dsn

    async def ensure_pool(self):
        """Lazily create the connection pool + initialize schema — called on first use, avoiding a construction-time DB connection failure."""
        if self._pool is not None:
            return self._pool
        import asyncpg
        self._pool = await asyncpg.create_pool(
            dsn=self._dsn, min_size=self._min_size, max_size=self._max_size,
        )
        async with self._pool.acquire() as conn:
            await conn.execute(_SCHEMA)
            for sql in _ADD_CRYPTO_COLS:
                await conn.execute(sql)
        logger.info("PostgresRepository connection pool ready: %s", self._dsn_redacted())
        return self._pool

    # ── Async API (used in cluster mode) ──

    async def asave_history(self, records: list[dict[str, Any]]) -> None:
        await self.ensure_pool()
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("DELETE FROM task_history")
                if records:
                    rows = [(r.get("ts", ""), json.dumps(r, ensure_ascii=False)) for r in records]
                    await conn.executemany(
                        "INSERT INTO task_history (ts, payload) VALUES ($1, $2)",
                        rows,
                    )

    async def aload_history(self) -> list[dict[str, Any]]:
        await self.ensure_pool()
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT payload FROM task_history ORDER BY id ASC")
        return [json.loads(r["payload"]) for r in rows]

    async def asave_name_map(
        self,
        name_map: dict[str, str],
        reverse_map: dict[str, str],
        cipher: object | None = None,
    ) -> None:
        # M1-T6: cipher non-None → name_hash(sha256)+name_encrypted(AES-GCM); None → plaintext compatibility.
        import hashlib

        await self.ensure_pool()
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("DELETE FROM name_map")
                rows = []
                for key, anon_id in name_map.items():
                    rev = reverse_map.get(anon_id, "")
                    if cipher is not None:
                        nh = hashlib.sha256(key.encode("utf-8")).hexdigest()
                        ne = cipher.encrypt(rev) if rev else ""
                        rows.append((key, anon_id, rev, nh, ne))
                    else:
                        rows.append((key, anon_id, rev, "", ""))
                if rows:
                    await conn.executemany(
                        "INSERT INTO name_map (map_key, anon_id, reverse, name_hash, name_encrypted) "
                        "VALUES ($1, $2, $3, $4, $5)",
                        rows,
                    )

    async def aload_name_map(
        self, cipher: object | None = None
    ) -> tuple[dict[str, str], dict[str, str]]:
        await self.ensure_pool()
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT map_key, anon_id, reverse, name_encrypted FROM name_map"
            )
        name_map: dict[str, str] = {}
        reverse_map: dict[str, str] = {}
        for r in rows:
            ne = r["name_encrypted"]
            if ne and cipher is not None:
                try:
                    real = cipher.decrypt(ne)
                except Exception as e:
                    logger.warning("name_map decryption failed, falling back to plaintext: %s", e)
                    real = r["reverse"]
                name_map[r["map_key"]] = r["anon_id"]
                if real:
                    reverse_map[r["anon_id"]] = real
            else:
                name_map[r["map_key"]] = r["anon_id"]
                if r["reverse"]:
                    reverse_map[r["anon_id"]] = r["reverse"]
        return name_map, reverse_map

    # ── Sync adapters (satisfy the Repository ABC; cluster mode actually uses async) ──
    # Sync methods should not be used directly in cluster mode (they block the loop); they exist
    # only for interface completeness and run a temporary loop internally.

    def save_history(self, records: list[dict[str, Any]]) -> None:
        import asyncio
        asyncio.get_event_loop().run_until_complete(self.asave_history(records))

    def load_history(self) -> list[dict[str, Any]]:
        import asyncio
        return asyncio.get_event_loop().run_until_complete(self.aload_history())

    def save_name_map(
        self,
        name_map: dict[str, str],
        reverse_map: dict[str, str],
        cipher: object | None = None,
    ) -> None:
        import asyncio
        asyncio.get_event_loop().run_until_complete(
            self.asave_name_map(name_map, reverse_map, cipher)
        )

    def load_name_map(
        self, cipher: object | None = None
    ) -> tuple[dict[str, str], dict[str, str]]:
        import asyncio
        return asyncio.get_event_loop().run_until_complete(self.aload_name_map(cipher))

    async def aclose(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            logger.info("PostgresRepository connection pool closed")

    def close(self) -> None:
        if self._pool is not None:
            import asyncio
            asyncio.get_event_loop().run_until_complete(self.aclose())

    async def ahealth(self) -> bool:
        try:
            await self.ensure_pool()
            async with self._pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return True
        except Exception as e:
            logger.warning("PostgresRepository health probe failed: %s", e)
            return False

    def health(self) -> bool:
        import asyncio
        return asyncio.get_event_loop().run_until_complete(self.ahealth())

    # ── M2-T11: task locks (async, used in cluster mode) ──

    @staticmethod
    def _now() -> float:
        import time
        return time.time()

    async def atry_lock(self, task_id: str, owner: str, ttl: float = 300.0) -> bool:
        await self.ensure_pool()
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM task_lock WHERE acquired_ts + ttl < $1", self._now()
                )
                row = await conn.fetchrow(
                    "SELECT owner FROM task_lock WHERE task_id = $1", task_id
                )
                now = self._now()
                if row is None:
                    await conn.execute(
                        "INSERT INTO task_lock (task_id, owner, acquired_ts, ttl) "
                        "VALUES ($1, $2, $3, $4)",
                        task_id, owner, now, ttl,
                    )
                    return True
                if row["owner"] == owner:
                    await conn.execute(
                        "UPDATE task_lock SET acquired_ts = $1, ttl = $2 "
                        "WHERE task_id = $3 AND owner = $4",
                        now, ttl, task_id, owner,
                    )
                    return True
                return False

    async def arenew_lock(self, task_id: str, owner: str, ttl: float = 300.0) -> bool:
        await self.ensure_pool()
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE task_lock SET acquired_ts = $1, ttl = $2 "
                "WHERE task_id = $3 AND owner = $4",
                self._now(), ttl, task_id, owner,
            )
            return result.endswith(" 1")

    async def arelease_lock(self, task_id: str, owner: str) -> None:
        await self.ensure_pool()
        async with self._pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM task_lock WHERE task_id = $1 AND owner = $2",
                task_id, owner,
            )

    async def areap_expired_locks(self) -> int:
        await self.ensure_pool()
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM task_lock WHERE acquired_ts + ttl < $1", self._now()
            )
            return int(result.split()[-1]) if result else 0

    # Sync adapters (satisfy the Repository ABC)
    def try_lock(self, task_id: str, owner: str, ttl: float = 300.0) -> bool:
        import asyncio
        return asyncio.get_event_loop().run_until_complete(
            self.atry_lock(task_id, owner, ttl)
        )

    def renew_lock(self, task_id: str, owner: str, ttl: float = 300.0) -> bool:
        import asyncio
        return asyncio.get_event_loop().run_until_complete(
            self.arenew_lock(task_id, owner, ttl)
        )

    def release_lock(self, task_id: str, owner: str) -> None:
        import asyncio
        asyncio.get_event_loop().run_until_complete(self.arelease_lock(task_id, owner))

    def reap_expired_locks(self) -> int:
        import asyncio
        return asyncio.get_event_loop().run_until_complete(self.areap_expired_locks())

    # ── M3-T14: audit persistence (async, used in cluster mode) ──

    async def asave_audit(self, records: list[dict[str, Any]]) -> None:
        if not records:
            return
        await self.ensure_pool()
        cols = (
            "ts", "trace_id", "route", "method", "status", "duration_ms",
            "student_hash", "llm_model", "llm_status", "client_ip", "error",
        )
        rows = []
        for r in records:
            row = []
            for c in cols:
                v = r.get(c, 0 if c in ("status", "duration_ms") else "")
                if c == "status":
                    v = int(v)
                elif c == "duration_ms":
                    v = float(v)
                else:
                    v = str(v)
                row.append(v)
            rows.append(tuple(row))
        async with self._pool.acquire() as conn:
            placeholders = ",".join(f"${i+1}" for i in range(len(cols)))
            await conn.executemany(
                f"INSERT INTO audit_events ({','.join(cols)}) VALUES ({placeholders})",
                rows,
            )

    async def aload_audit(
        self, since_ts: str = "", limit: int = 1000
    ) -> list[dict[str, Any]]:
        await self.ensure_pool()
        cols = (
            "ts", "trace_id", "route", "method", "status", "duration_ms",
            "student_hash", "llm_model", "llm_status", "client_ip", "error",
        )
        async with self._pool.acquire() as conn:
            if since_ts:
                rows = await conn.fetch(
                    f"SELECT {','.join(cols)} FROM audit_events WHERE ts >= $1 "
                    f"ORDER BY id ASC LIMIT $2",
                    since_ts, limit,
                )
                return [dict(zip(cols, r)) for r in rows]
            rows = await conn.fetch(
                f"SELECT {','.join(cols)} FROM audit_events "
                f"ORDER BY id DESC LIMIT $1",
                limit,
            )
        return [dict(zip(cols, r)) for r in reversed(rows)]

    async def apurge_audit(self, before_ts: str) -> int:
        await self.ensure_pool()
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM audit_events WHERE ts < $1", before_ts
            )
            return int(result.split()[-1]) if result else 0

    # Sync adapters
    def save_audit(self, records: list[dict[str, Any]]) -> None:
        import asyncio
        asyncio.get_event_loop().run_until_complete(self.asave_audit(records))

    def load_audit(self, since_ts: str = "", limit: int = 1000) -> list[dict[str, Any]]:
        import asyncio
        return asyncio.get_event_loop().run_until_complete(self.aload_audit(since_ts, limit))

    def purge_audit(self, before_ts: str) -> int:
        import asyncio
        return asyncio.get_event_loop().run_until_complete(self.apurge_audit(before_ts))
