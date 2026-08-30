"""配置模块 — M3-T17。

提供者: EnvProvider (静态 env) / FileProvider (mtime 轮询)。
get_config() 工厂: FUSION_K12_CONFIG_FILE 指定文件则用 FileProvider, 否则 EnvProvider。
后台线程轮询刷新可热更新项 (model/限流/salt/日志级别), 变更回调刷新引擎持有配置。
"""

from __future__ import annotations

import logging
import os

from .env_provider import EnvProvider
from .file_provider import FileProvider
from .provider import HOT_RELOADABLE, ConfigProvider

logger = logging.getLogger(__name__)

__all__ = [
    "HOT_RELOADABLE",
    "ConfigProvider",
    "EnvProvider",
    "FileProvider",
    "get_config",
]

_config: ConfigProvider | None = None


def get_config() -> ConfigProvider:
    """单例配置提供者工厂。

    FUSION_K12_CONFIG_FILE 指定配置文件 → FileProvider (可热更);
    否则 EnvProvider (静态)。惰性建, 首次调用后不变。
    """
    global _config
    if _config is not None:
        return _config
    cfg_path = os.environ.get("FUSION_K12_CONFIG_FILE", "")
    if cfg_path and os.path.exists(cfg_path):
        _config = FileProvider(cfg_path)
        logger.info("使用 FileProvider 配置: %s", cfg_path)
    else:
        _config = EnvProvider()
        logger.info("使用 EnvProvider 配置 (静态)")
    return _config


def reset_config() -> None:
    """重置单例 — 测试用。"""
    global _config
    if _config is not None:
        try:
            _config.stop()
        except Exception:
            pass
    _config = None
