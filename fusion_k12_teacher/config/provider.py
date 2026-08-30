"""配置提供者抽象 — M3-T17。

可热更新配置项后台轮询, 变更回调刷新引擎持有的可变配置 (model/限流/日志级别),
不重建引擎。不可热更新项 (DB/端口/data_key) 启动注入, 改则滚动重启 — 不经此。
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

logger = logging.getLogger(__name__)

# 可热更新项白名单 — 仅这些 key 的变更会被回调应用
HOT_RELOADABLE = (
    "FUSION_MLX_MODEL",
    "FUSION_K12_RATE_LIMIT",
    "FUSION_K12_SALT",
    "FUSION_K12_LOG_LEVEL",
)


class ConfigProvider:
    """配置提供者基类 — get + 后台轮询 + 变更回调。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._callbacks: list[Callable[[str, str], None]] = []
        self._poll_thread: threading.Thread | None = None
        self._poll_stop = threading.Event()
        self._poll_interval = float(__import__("os").environ.get("FUSION_K12_CONFIG_POLL", "5"))

    def get(self, key: str, default: str = "") -> str:
        """取配置值 — 子类实现实际读取。"""
        return default

    def refresh(self) -> dict[str, str]:
        """重新读取, 返回本次变更的 {key: new_value}。基类空实现。"""
        return {}

    def on_change(self, cb: Callable[[str, str], None]) -> None:
        """注册变更回调 cb(key, new_value)。"""
        self._callbacks.append(cb)

    def start(self) -> None:
        """启动后台轮询线程 — 仅 FileProvider 等可变源需要, 静态源 no-op。"""
        if self._poll_thread is not None:
            return
        self._poll_stop.clear()
        self._poll_thread = threading.Thread(
            target=self._poll_loop, name="k12-config-poll", daemon=True
        )
        self._poll_thread.start()
        logger.info("配置轮询线程已启动 interval=%ss", self._poll_interval)

    def stop(self) -> None:
        """停止轮询线程。"""
        self._poll_stop.set()
        t = self._poll_thread
        if t is not None:
            t.join(timeout=self._poll_interval + 2)
            self._poll_thread = None
        logger.info("配置轮询线程已停止")

    def _poll_loop(self) -> None:
        """轮询循环 — 检测变更触发回调。"""
        while not self._poll_stop.is_set():
            if self._poll_stop.wait(self._poll_interval):
                break
            try:
                changed = self.refresh()
            except Exception as e:
                logger.warning("配置轮询刷新失败: %s", e)
                continue
            if not changed:
                continue
            for key, val in changed.items():
                if key not in HOT_RELOADABLE:
                    continue
                logger.info("配置热更新: %s = %s", key, _redact(key, val))
                for cb in list(self._callbacks):
                    try:
                        cb(key, val)
                    except Exception as e:
                        logger.warning("配置变更回调 %s 失败: %s", getattr(cb, "__name__", cb), e)


def _redact(key: str, val: str) -> str:
    """敏感配置值脱敏 — salt 不打明文。"""
    if "SALT" in key or "KEY" in key:
        return f"<{len(val)} chars>"
    return val
