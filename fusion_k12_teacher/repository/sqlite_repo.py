"""SQLite Repository — standalone 模式后端。

stdlib sqlite3, 零外部依赖。history 整列表覆写改为单表行存 (带自增 id),
name_map KV 表。并发靠 sqlite3 文件锁 + 短事务。
"""

from __future__ import annotations

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
"""


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

    def save_name_map(self, name_map: dict[str, str], reverse_map: dict[str, str]) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("DELETE FROM name_map")
            rows = []
            for key, anon_id in name_map.items():
                # map_key 形如 "name\x00seq", reverse 按 anon_id 查原名
                rev = reverse_map.get(anon_id, "")
                rows.append((key, anon_id, rev))
            cur.executemany(
                "INSERT INTO name_map (map_key, anon_id, reverse) VALUES (?, ?, ?)",
                rows,
            )
            self._conn.commit()

    def load_name_map(self) -> tuple[dict[str, str], dict[str, str]]:
        with self._lock:
            cur = self._conn.execute("SELECT map_key, anon_id, reverse FROM name_map")
            name_map: dict[str, str] = {}
            reverse_map: dict[str, str] = {}
            for map_key, anon_id, rev in cur.fetchall():
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
