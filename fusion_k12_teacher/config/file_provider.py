"""配置文件提供者 — mtime 轮询触发 reload。

读 KEY=VALUE 行 (shell-style), 文件 mtime 变更即重新加载, 仅可热更新项触发回调。
"""

from __future__ import annotations

import logging
import os

from .provider import HOT_RELOADABLE, ConfigProvider

logger = logging.getLogger(__name__)


class FileProvider(ConfigProvider):
    """配置文件提供者 — mtime 变更触发 reload。"""

    def __init__(self, path: str) -> None:
        super().__init__()
        self._path = path
        self._mtime: float = 0.0
        self._values: dict[str, str] = {}
        self._refresh()

    def _refresh(self) -> None:
        """读文件至内存, 记 mtime。文件不存在则空。"""
        try:
            st = os.stat(self._path)
            self._mtime = st.st_mtime
        except FileNotFoundError:
            logger.warning("配置文件不存在: %s", self._path)
            self._mtime = 0.0
            self._values = {}
            return
        self._values = _parse_file(self._path)

    def get(self, key: str, default: str = "") -> str:
        return self._values.get(key, default)

    def refresh(self) -> dict[str, str]:
        """mtime 变更则重读, 返回可热更新项的变更。"""
        try:
            st = os.stat(self._path)
        except FileNotFoundError:
            logger.warning("配置文件消失: %s", self._path)
            return {}
        if st.st_mtime == self._mtime:
            return {}
        logger.info("配置文件变更, reload: %s", self._path)
        old = self._values
        self._mtime = st.st_mtime
        self._values = _parse_file(self._path)
        changed: dict[str, str] = {}
        for key in HOT_RELOADABLE:
            nv = self._values.get(key, "")
            ov = old.get(key, "")
            if nv != ov and nv:
                changed[key] = nv
        return changed


def _parse_file(path: str) -> dict[str, str]:
    """解析 KEY=VALUE 文件 — 跳过空行/# 注释, 去首尾空白。"""
    values: dict[str, str] = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                v = v.strip()
                if k:
                    values[k] = v
    except OSError as e:
        logger.warning("配置文件读失败 %s: %s", path, e)
    return values
