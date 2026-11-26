# Config module — M3-T17.
#
# Providers: EnvProvider (static env) / FileProvider (mtime polling).
# The get_config() factory uses FileProvider when FUSION_K12_CONFIG_FILE points to
# a file, otherwise EnvProvider.
# A background thread polls and refreshes hot-reloadable items (model/rate
# limit/salt/log level); change callbacks refresh engine-held config.

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


# Singleton config provider factory.
#
#     FUSION_K12_CONFIG_FILE pointing at a config file -> FileProvider (hot
#     reload); otherwise EnvProvider (static). Built lazily, fixed after the
#     first call.
def get_config() -> ConfigProvider:
    global _config
    if _config is not None:
        return _config
    cfg_path = os.environ.get("FUSION_K12_CONFIG_FILE", "")
    if cfg_path and os.path.exists(cfg_path):
        _config = FileProvider(cfg_path)
        logger.info("Using FileProvider config: %s", cfg_path)
    else:
        _config = EnvProvider()
        logger.info("Using EnvProvider config (static)")
    return _config


# Reset the singleton — for tests.
def reset_config() -> None:
    global _config
    if _config is not None:
        try:
            _config.stop()
        except Exception:
            pass
    _config = None
