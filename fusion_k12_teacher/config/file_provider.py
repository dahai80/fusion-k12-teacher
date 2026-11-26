"""Config file provider — mtime polling triggers reload.

Reads KEY=VALUE lines (shell-style); reloads when the file mtime changes;
only hot-reloadable items trigger callbacks.
"""

from __future__ import annotations

import logging
import os

from .provider import HOT_RELOADABLE, ConfigProvider

logger = logging.getLogger(__name__)


class FileProvider(ConfigProvider):
    """Config file provider — mtime change triggers reload."""

    def __init__(self, path: str) -> None:
        super().__init__()
        self._path = path
        self._mtime: float = 0.0
        self._values: dict[str, str] = {}
        self._refresh()

    def _refresh(self) -> None:
        """Read the file into memory and record mtime. Empty when the file is missing."""
        try:
            st = os.stat(self._path)
            self._mtime = st.st_mtime
        except FileNotFoundError:
            logger.warning("Config file does not exist: %s", self._path)
            self._mtime = 0.0
            self._values = {}
            return
        self._values = _parse_file(self._path)

    def get(self, key: str, default: str = "") -> str:
        return self._values.get(key, default)

    def refresh(self) -> dict[str, str]:
        """Re-read when mtime changed; return changes to hot-reloadable items."""
        try:
            st = os.stat(self._path)
        except FileNotFoundError:
            logger.warning("Config file disappeared: %s", self._path)
            return {}
        if st.st_mtime == self._mtime:
            return {}
        logger.info("Config file changed, reload: %s", self._path)
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
    """Parse a KEY=VALUE file — skips empty lines/# comments, strips whitespace."""
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
        logger.warning("Failed to read config file %s: %s", path, e)
    return values
