# Environment variable provider — single-machine default, static read at startup.
#
# Snapshots env at startup and never changes at runtime (no polling). Changes
# require a restart or rolling restart.

from __future__ import annotations

import logging
import os

from .provider import ConfigProvider

logger = logging.getLogger(__name__)


# Static env provider — startup snapshot, no hot reload.
class EnvProvider(ConfigProvider):

    def __init__(self) -> None:
        super().__init__()
        self._snapshot: dict[str, str] = dict(os.environ)
        logger.info("EnvProvider initialized, %d entries in snapshot", len(self._snapshot))

    def get(self, key: str, default: str = "") -> str:
        return self._snapshot.get(key, default)

    def refresh(self) -> dict[str, str]:
        return {}
