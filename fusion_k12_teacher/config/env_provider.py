"""环境变量提供者 — 单机默认, 启动读静态。

启动时快照 env, 运行期不变 (不轮询)。变更需重启或滚动重启。
"""

from __future__ import annotations

import logging
import os

from .provider import ConfigProvider

logger = logging.getLogger(__name__)


class EnvProvider(ConfigProvider):
    """静态 env 提供者 — 启动快照, 不热更新。"""

    def __init__(self) -> None:
        super().__init__()
        self._snapshot: dict[str, str] = dict(os.environ)
        logger.info("EnvProvider 初始化, 快照 %d 项", len(self._snapshot))

    def get(self, key: str, default: str = "") -> str:
        return self._snapshot.get(key, default)

    def refresh(self) -> dict[str, str]:
        return {}
