"""SQLite Repository — standalone 模式后端。

stdlib sqlite3, 零外部依赖。history 整列表覆写改为单表行存 (带自增 id),
name_map KV 表。并发靠 sqlite3 文件锁 + 短事务。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import threading
from typing import Any

from .base import Repository

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS task_history (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
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
    acquired_ts REAL    NOT NULL,
    ttl         REAL    NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT    NOT NULL,
    trace_id     TEXT    NOT NULL DEFAULT '',
    route        TEXT    NOT NULL DEFAULT '',
    method       TEXT    NOT NULL DEFAULT '',
    status       INTEGER NOT NULL DEFAULT 0,
    duration_ms  REAL    NOT NULL DEFAULT 0,
    student_hash TEXT    NOT NULL DEFAULT '',
    llm_model    TEXT    NOT NULL DEFAULT '',
    llm_status   TEXT    NOT NULL DEFAULT '',
    client_ip    TEXT    NOT NULL DEFAULT '',
    error        TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_events(ts);
CREATE TABLE IF NOT EXISTS teachers (
    id            TEXT PRIMARY KEY,
    username      TEXT UNIQUE NOT NULL,
    name          TEXT NOT NULL DEFAULT '',
    school        TEXT NOT NULL DEFAULT '',
    region        TEXT NOT NULL DEFAULT '',
    default_edition TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    teacher_id TEXT NOT NULL,
    expires_at REAL    NOT NULL
);
CREATE TABLE IF NOT EXISTS materials (
    id           TEXT PRIMARY KEY,
    teacher_id   TEXT NOT NULL,
    edition      TEXT NOT NULL DEFAULT '',
    subject      TEXT NOT NULL DEFAULT '',
    grade        TEXT NOT NULL DEFAULT '',
    lesson_id    TEXT NOT NULL DEFAULT '',
    unit_title   TEXT NOT NULL DEFAULT '',
    lesson_title TEXT NOT NULL DEFAULT '',
    type         TEXT NOT NULL,
    title        TEXT NOT NULL DEFAULT '',
    payload      TEXT NOT NULL,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_materials_teacher ON materials(teacher_id);
"""

# M1-T6: 加密列 — name_hash (sha256 查询键, 无明文) + name_encrypted (AES-GCM 可逆)。
# 旧列 map_key/reverse 保留兼容明文模式; 加密模式写新列, map_key 置空。
_ADD_CRYPTO_COLS = [
    "ALTER TABLE name_map ADD COLUMN name_hash TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE name_map ADD COLUMN name_encrypted TEXT NOT NULL DEFAULT ''",
]


def _ensure_crypto_cols(conn) -> None:
    for sql in _ADD_CRYPTO_COLS:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            # 列已存在
            pass


class SQLiteRepository(Repository):
    """单机 SQLite 持久化后端。

    单连接 + 模块级锁, 单进程串行写。standalone 模式够用;
    多进程/多实例需 PostgresRepository (M1-T2)。
    """

    def __init__(self, db_path: str):
        self._db_path = os.path.expanduser(db_path)
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(self._db_path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript(_SCHEMA)
        _ensure_crypto_cols(self._conn)
        self._conn.commit()
        logger.info("SQLiteRepository 就绪: %s", self._db_path)

    def save_history(self, records: list[dict[str, Any]]) -> None:
        # 整列表覆写语义: 清表后批量插, 保持与旧 history.json 行为一致。
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("DELETE FROM task_history")
            cur.executemany(
                "INSERT INTO task_history (ts, payload) VALUES (?, ?)",
                [(r.get("ts", ""), json.dumps(r, ensure_ascii=False)) for r in records],
            )
            self._conn.commit()

    def load_history(self) -> list[dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT payload FROM task_history ORDER BY id ASC"
            )
            return [json.loads(row[0]) for row in cur.fetchall()]

    def save_name_map(
        self,
        name_map: dict[str, str],
        reverse_map: dict[str, str],
        cipher: object | None = None,
    ) -> None:
        # M1-T6: cipher 非空 → 加密模式。name_hash=sha256(map_key) 作查询键(无明文),
        # name_encrypted=AES-GCM(原名) 可逆回查。map_key/reverse 置空。
        # cipher 为空 → 明文模式 (v1.3.0 兼容), 写 map_key/reverse。
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("DELETE FROM name_map")
            rows = []
            for key, anon_id in name_map.items():
                rev = reverse_map.get(anon_id, "")
                if cipher is not None:
                    nh = hashlib.sha256(key.encode("utf-8")).hexdigest()
                    ne = cipher.encrypt(rev) if rev else ""
                    rows.append((key, anon_id, rev, nh, ne))
                else:
                    rows.append((key, anon_id, rev, "", ""))
            cur.executemany(
                "INSERT INTO name_map (map_key, anon_id, reverse, name_hash, name_encrypted) "
                "VALUES (?, ?, ?, ?, ?)",
                rows,
            )
            self._conn.commit()

    def load_name_map(
        self, cipher: object | None = None
    ) -> tuple[dict[str, str], dict[str, str]]:
        # M1-T6: 优先读加密列 (name_encrypted 有值即加密行), cipher 解密还原原名。
        # 无 cipher 或加密列空 → 回退明文 map_key/reverse (兼容旧库/明文模式)。
        with self._lock:
            cur = self._conn.execute(
                "SELECT map_key, anon_id, reverse, name_encrypted FROM name_map"
            )
            name_map: dict[str, str] = {}
            reverse_map: dict[str, str] = {}
            for map_key, anon_id, rev, ne in cur.fetchall():
                if ne and cipher is not None:
                    try:
                        real = cipher.decrypt(ne)
                    except Exception as e:
                        logger.warning("name_map 解密失败, 回退明文: %s", e)
                        real = rev
                    # 加密模式键用 map_key (调用方传 name\x00seq), 还原原名入反向表
                    name_map[map_key] = anon_id
                    if real:
                        reverse_map[anon_id] = real
                else:
                    name_map[map_key] = anon_id
                    if rev:
                        reverse_map[anon_id] = rev
            return name_map, reverse_map

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
                logger.info("SQLiteRepository 已关闭: %s", self._db_path)
            except Exception as e:
                logger.warning("关闭 SQLiteRepository 失败: %s", e)

    def health(self) -> bool:
        try:
            with self._lock:
                self._conn.execute("SELECT 1").fetchone()
            return True
        except Exception as e:
            logger.warning("SQLiteRepository 健康探测失败: %s", e)
            return False

    # ── M2-T11: 任务锁 ──

    @staticmethod
    def _now() -> float:
        import time
        return time.time()

    def try_lock(self, task_id: str, owner: str, ttl: float = 300.0) -> bool:
        # 先 reap 超时锁, 再尝试插入; 同 owner 重入视为续约成功。
        with self._lock:
            now = self._now()
            self._conn.execute(
                "DELETE FROM task_lock WHERE acquired_ts + ttl < ?", (now,)
            )
            row = self._conn.execute(
                "SELECT owner, acquired_ts, ttl FROM task_lock WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if row is None:
                self._conn.execute(
                    "INSERT INTO task_lock (task_id, owner, acquired_ts, ttl) VALUES (?, ?, ?, ?)",
                    (task_id, owner, now, ttl),
                )
                self._conn.commit()
                return True
            if row[0] == owner:
                # 同 owner 重入: 续约
                self._conn.execute(
                    "UPDATE task_lock SET acquired_ts = ?, ttl = ? WHERE task_id = ? AND owner = ?",
                    (now, ttl, task_id, owner),
                )
                self._conn.commit()
                return True
            self._conn.commit()
            return False

    def renew_lock(self, task_id: str, owner: str, ttl: float = 300.0) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE task_lock SET acquired_ts = ?, ttl = ? WHERE task_id = ? AND owner = ?",
                (self._now(), ttl, task_id, owner),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def release_lock(self, task_id: str, owner: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM task_lock WHERE task_id = ? AND owner = ?",
                (task_id, owner),
            )
            self._conn.commit()

    def reap_expired_locks(self) -> int:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM task_lock WHERE acquired_ts + ttl < ?",
                (self._now(),),
            )
            self._conn.commit()
            return cur.rowcount

    # ── M3-T14: 审计持久化 ──

    def save_audit(self, records: list[dict[str, Any]]) -> None:
        if not records:
            return
        cols = (
            "ts", "trace_id", "route", "method", "status", "duration_ms",
            "student_hash", "llm_model", "llm_status", "client_ip", "error",
        )
        placeholders = ",".join("?" * len(cols))
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
        with self._lock:
            self._conn.executemany(
                f"INSERT INTO audit_events ({','.join(cols)}) VALUES ({placeholders})",
                rows,
            )
            self._conn.commit()

    def load_audit(self, since_ts: str = "", limit: int = 1000) -> list[dict[str, Any]]:
        cols = (
            "ts", "trace_id", "route", "method", "status", "duration_ms",
            "student_hash", "llm_model", "llm_status", "client_ip", "error",
        )
        with self._lock:
            if since_ts:
                cur = self._conn.execute(
                    f"SELECT {','.join(cols)} FROM audit_events WHERE ts >= ? "
                    f"ORDER BY id ASC LIMIT ?",
                    (since_ts, limit),
                )
            else:
                cur = self._conn.execute(
                    f"SELECT {','.join(cols)} FROM audit_events "
                    f"ORDER BY id DESC LIMIT ?",
                    (limit,),
                )
            rows = cur.fetchall()
        if since_ts:
            return [dict(zip(cols, r)) for r in rows]
        # 无 since: DESC 取 recent, 返回时按时间正序
        return [dict(zip(cols, r)) for r in reversed(rows)]

    def purge_audit(self, before_ts: str) -> int:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM audit_events WHERE ts < ?", (before_ts,)
            )
            self._conn.commit()
            return cur.rowcount

    # ── 教师身份 ──

    _TEACHER_COLS = (
        "id", "username", "name", "school", "region",
        "default_edition", "password_hash", "created_at",
    )

    def create_teacher(self, teacher: dict[str, Any]) -> str:
        cols = self._TEACHER_COLS
        vals = [str(teacher.get(c, "")) for c in cols]
        placeholders = ",".join("?" * len(cols))
        with self._lock:
            self._conn.execute(
                f"INSERT INTO teachers ({','.join(cols)}) VALUES ({placeholders})",
                vals,
            )
            self._conn.commit()
        return str(teacher.get("id", ""))

    def _row_to_teacher(self, row) -> dict[str, Any]:
        return dict(zip(self._TEACHER_COLS, row))

    def get_teacher_by_username(self, username: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                f"SELECT {','.join(self._TEACHER_COLS)} FROM teachers WHERE username = ?",
                (username,),
            ).fetchone()
        return self._row_to_teacher(row) if row else None

    def get_teacher(self, teacher_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                f"SELECT {','.join(self._TEACHER_COLS)} FROM teachers WHERE id = ?",
                (teacher_id,),
            ).fetchone()
        return self._row_to_teacher(row) if row else None

    def create_session(self, token: str, teacher_id: str, expires_at: float) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO sessions (token, teacher_id, expires_at) VALUES (?, ?, ?)",
                (token, teacher_id, expires_at),
            )
            self._conn.commit()

    def get_session(self, token: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT token, teacher_id, expires_at FROM sessions WHERE token = ?",
                (token,),
            ).fetchone()
        if not row:
            return None
        return {"token": row[0], "teacher_id": row[1], "expires_at": row[2]}

    def delete_session(self, token: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            self._conn.commit()

    # ── 资源库 ──

    _MATERIAL_COLS = (
        "id", "teacher_id", "edition", "subject", "grade", "lesson_id",
        "unit_title", "lesson_title", "type", "title", "payload", "created_at",
    )

    def save_material(self, material: dict[str, Any]) -> str:
        cols = self._MATERIAL_COLS
        vals = [str(material.get(c, "")) for c in cols]
        placeholders = ",".join("?" * len(cols))
        with self._lock:
            self._conn.execute(
                f"INSERT INTO materials ({','.join(cols)}) VALUES ({placeholders})",
                vals,
            )
            self._conn.commit()
        return str(material.get("id", ""))

    def list_materials(
        self,
        teacher_id: str,
        *,
        type: str | None = None,
        subject: str | None = None,
        grade: str | None = None,
        lesson_id: str | None = None,
        edition: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        cols = self._MATERIAL_COLS
        where = ["teacher_id = ?"]
        params: list[Any] = [teacher_id]
        if type:
            where.append("type = ?")
            params.append(type)
        if subject:
            where.append("subject = ?")
            params.append(subject)
        if grade:
            where.append("grade = ?")
            params.append(grade)
        if lesson_id:
            where.append("lesson_id = ?")
            params.append(lesson_id)
        if edition:
            where.append("edition = ?")
            params.append(edition)
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {','.join(cols)} FROM materials WHERE {' AND '.join(where)} "
                f"ORDER BY id DESC LIMIT ?",
                params,
            ).fetchall()
        return [dict(zip(cols, r)) for r in rows]

    def get_material(self, material_id: str) -> dict[str, Any] | None:
        cols = self._MATERIAL_COLS
        with self._lock:
            row = self._conn.execute(
                f"SELECT {','.join(cols)} FROM materials WHERE id = ?",
                (material_id,),
            ).fetchone()
        return dict(zip(cols, row)) if row else None

    def delete_material(self, material_id: str, teacher_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM materials WHERE id = ? AND teacher_id = ?",
                (material_id, teacher_id),
            )
            self._conn.commit()
            return cur.rowcount > 0
