"""Repository 抽象层 — v2.0 持久化解耦。

业务层面向 Repository 接口编程, 不感知具体后端 (SQLite/Postgres)。
standalone 模式用 SQLiteRepository, cluster 模式用 PostgresRepository (M1-T2)。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class Repository(ABC):
    """持久化仓库抽象基类。

    每个 entity (history/name_map/audit) 一组读写方法。
    后端实现负责序列化/并发/事务, 调用方仅传结构化 dict。
    """

    @abstractmethod
    def save_history(self, records: list[dict[str, Any]]) -> None:
        """覆写式保存任务执行历史 (整列表)。"""

    @abstractmethod
    def load_history(self) -> list[dict[str, Any]]:
        """加载全部任务执行历史 (按时间升序)。"""

    @abstractmethod
    def save_name_map(self, name_map: dict[str, str], reverse_map: dict[str, str]) -> None:
        """保存脱敏映射表 (name→id 正向 + id→name 反向)。"""

    @abstractmethod
    def load_name_map(self) -> tuple[dict[str, str], dict[str, str]]:
        """加载脱敏映射表, 返回 (name_map, reverse_map)。"""

    # ── M2-T11: 任务锁 (跨实例 cron 去重) ──
    # cluster 模式多实例各 arm cron, 抢 DB 行锁防同一任务重复执行。
    # owner = 实例标识 (hostname+pid), ttl = 锁超时秒 (防持锁实例宕机永久阻塞)。

    def try_lock(self, task_id: str, owner: str, ttl: float = 300.0) -> bool:
        """尝试获取任务执行锁 — 成功返 True, 已被持有(且未超时)返 False。

        幂等: 同 owner 再次获取返 True (重入/续约场景)。
        ttl 超时的旧锁被 reap 后可重新获取。
        默认实现 (standalone 单进程无需 DB 锁) 总返 True。
        """
        return True

    def renew_lock(self, task_id: str, owner: str, ttl: float = 300.0) -> bool:
        """续约任务锁 — 仅持锁 owner 可续, 成功返 True。默认空实现。"""
        return True

    def release_lock(self, task_id: str, owner: str) -> None:
        """释放任务锁 — 仅持锁 owner 可释放。默认空实现。"""

    def reap_expired_locks(self) -> int:
        """清理超时锁 — 返回清理条数。默认空实现返 0。"""
        return 0

    def close(self) -> None:
        """释放后端资源 (连接/文件句柄)。默认空实现。"""

    def health(self) -> bool:
        """后端健康探测, 供 /api/ready 用。默认 True。"""
        return True
