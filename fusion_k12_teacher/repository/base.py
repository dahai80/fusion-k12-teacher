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

    def close(self) -> None:
        """释放后端资源 (连接/文件句柄)。默认空实现。"""

    def health(self) -> bool:
        """后端健康探测, 供 /api/ready 用。默认 True。"""
        return True
