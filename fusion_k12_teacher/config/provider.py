# Config provider abstraction — M3-T17.
#
# Hot-reloadable config keys are polled in the background; change callbacks refresh
# the mutable config held by engines (model/rate limit/log level) without rebuilding
# engines. Non-hot-reloadable items (DB/port/data_key) are injected at startup;
# changing them requires a rolling restart — they do not go through here.

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

logger = logging.getLogger(__name__)

# Hot-reloadable key whitelist — only changes to these keys are applied via callbacks
HOT_RELOADABLE = (
    "FUSION_MLX_MODEL",
    "FUSION_K12_RATE_LIMIT",
    "FUSION_K12_SALT",
    "FUSION_K12_LOG_LEVEL",
)


# Config provider base class — get + background polling + change callbacks.
class ConfigProvider:

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._callbacks: list[Callable[[str, str], None]] = []
        self._poll_thread: threading.Thread | None = None
        self._poll_stop = threading.Event()
        self._poll_interval = float(__import__("os").environ.get("FUSION_K12_CONFIG_POLL", "5"))

    # Read a config value — subclasses implement the actual read.
    def get(self, key: str, default: str = "") -> str:
        return default

    # Re-read config, return {key: new_value} changed this round. Base class is a no-op.
    def refresh(self) -> dict[str, str]:
        return {}

    # Register a change callback cb(key, new_value).
    def on_change(self, cb: Callable[[str, str], None]) -> None:
        self._callbacks.append(cb)

    # Start the background polling thread — only mutable sources like FileProvider need it, static sources are no-op.
    def start(self) -> None:
        if self._poll_thread is not None:
            return
        self._poll_stop.clear()
        self._poll_thread = threading.Thread(
            target=self._poll_loop, name="k12-config-poll", daemon=True
        )
        self._poll_thread.start()
        logger.info("Config polling thread started interval=%ss", self._poll_interval)

    # Stop the polling thread.
    def stop(self) -> None:
        self._poll_stop.set()
        t = self._poll_thread
        if t is not None:
            t.join(timeout=self._poll_interval + 2)
            self._poll_thread = None
        logger.info("Config polling thread stopped")

    # Polling loop — detect changes and trigger callbacks.
    def _poll_loop(self) -> None:
        while not self._poll_stop.is_set():
            if self._poll_stop.wait(self._poll_interval):
                break
            try:
                changed = self.refresh()
            except Exception as e:
                logger.warning("Config polling refresh failed: %s", e)
                continue
            if not changed:
                continue
            for key, val in changed.items():
                if key not in HOT_RELOADABLE:
                    continue
                logger.info("Config hot-reload: %s = %s", key, _redact(key, val))
                for cb in list(self._callbacks):
                    try:
                        cb(key, val)
                    except Exception as e:
                        logger.warning("Config change callback %s failed: %s", getattr(cb, "__name__", cb), e)


# Redact sensitive config values — never log salt in plaintext.
def _redact(key: str, val: str) -> str:
    if "SALT" in key or "KEY" in key:
        return f"<{len(val)} chars>"
    return val
