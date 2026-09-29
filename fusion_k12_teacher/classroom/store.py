"""课堂持久化 — SQLite 存课程包/会话, 复用 repository db 路径模式。

独立表 classroom_packages / classroom_sessions, 不侵入现有 repository schema。
并发安全: sqlite3 默认 serialized, 额外加 threading.Lock 防写冲突。
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_DB = os.path.expanduser(
    os.environ.get("FUSION_K12_CLASSROOM_DB", "~/.fusion-k12/classroom.db")
)


class ClassroomStore:
    def __init__(self, db_path: str = "") -> None:
        self._db = db_path or _DEFAULT_DB
        Path(self._db).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_schema()
        logger.info("classroom_store: 初始化 db=%s", self._db)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                """CREATE TABLE IF NOT EXISTS classroom_packages (
                    class_id TEXT PRIMARY KEY, code TEXT UNIQUE,
                    subject TEXT, grade TEXT, topic TEXT,
                    payload TEXT NOT NULL, created_at REAL
                )"""
            )
            c.execute(
                """CREATE TABLE IF NOT EXISTS classroom_sessions (
                    session_id TEXT PRIMARY KEY, class_id TEXT,
                    student_id TEXT, status TEXT,
                    started_at REAL, finished_at REAL,
                    payload TEXT NOT NULL,
                    UNIQUE(class_id, student_id)
                )"""
            )
            c.execute("CREATE INDEX IF NOT EXISTS idx_session_class ON classroom_sessions(class_id)")
            c.commit()

    def save_package(self, pkg: dict[str, Any]) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                """INSERT OR REPLACE INTO classroom_packages
                   (class_id, code, subject, grade, topic, payload, created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (pkg["class_id"], pkg["code"], pkg.get("subject", ""),
                 pkg.get("grade", ""), pkg.get("topic", ""),
                 json.dumps(pkg, ensure_ascii=False), pkg.get("created_at", 0.0)),
            )
            c.commit()

    def get_package_by_id(self, class_id: str) -> dict[str, Any] | None:
        return self._get_package("class_id = ?", (class_id,))

    def get_package_by_code(self, code: str) -> dict[str, Any] | None:
        return self._get_package("code = ?", (code,))

    def _get_package(self, where: str, args: tuple) -> dict[str, Any] | None:
        with self._lock, self._conn() as c:
            row = c.execute(
                f"SELECT payload FROM classroom_packages WHERE {where}", args
            ).fetchone()
            if not row:
                return None
            try:
                return json.loads(row["payload"])
            except Exception as exc:
                logger.warning("classroom_store: 包 JSON 解析失败 %s", exc)
                return None

    def list_packages(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT payload FROM classroom_packages ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            out = []
            for r in rows:
                try:
                    out.append(json.loads(r["payload"]))
                except Exception:
                    pass
            return out

    def save_session(self, sess: dict[str, Any]) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                """INSERT OR REPLACE INTO classroom_sessions
                   (session_id, class_id, student_id, status,
                    started_at, finished_at, payload)
                   VALUES (?,?,?,?,?,?,?)""",
                (sess["session_id"], sess["class_id"], sess.get("student_id", ""),
                 sess.get("status", "active"), sess.get("started_at", 0.0),
                 sess.get("finished_at", 0.0), json.dumps(sess, ensure_ascii=False)),
            )
            c.commit()

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._lock, self._conn() as c:
            row = c.execute(
                "SELECT payload FROM classroom_sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            if not row:
                return None
            try:
                return json.loads(row["payload"])
            except Exception as exc:
                logger.warning("classroom_store: 会话 JSON 解析失败 %s", exc)
                return None

    def list_sessions(self, class_id: str = "", limit: int = 100) -> list[dict[str, Any]]:
        with self._lock, self._conn() as c:
            if class_id:
                rows = c.execute(
                    "SELECT payload FROM classroom_sessions WHERE class_id=? ORDER BY started_at DESC LIMIT ?",
                    (class_id, limit),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT payload FROM classroom_sessions ORDER BY started_at DESC LIMIT ?", (limit,)
                ).fetchall()
            out = []
            for r in rows:
                try:
                    out.append(json.loads(r["payload"]))
                except Exception:
                    pass
            return out

    def close(self) -> None:
        pass
