"""#34 (config Phase 2.2): 网关凭据单点解析。

config-conventions §1/§2: 唯一实现在 fusion_core.config — 各仓禁止自抄
解析逻辑。fusion_core 为可选依赖 (.[core]), 缺席时回退语义等价的旧 env
读取, 保证隔离环境行为不回退。
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def gateway_client_key() -> str:
    # FUSION_CLIENT_KEY 规范名 (别名链收敛在 fusion_core); dev 缺省空+警告,
    # FUSION_PROFILE=prod 缺省 RuntimeError — 语义见 fusion_core.config。
    try:
        from fusion_core.config import client_key
    except ImportError:
        # issue #35: 裸装回退只认规范名 FUSION_CLIENT_KEY — 别名链只活在
        # fusion_core, 本仓不重复 (pattern: fusion-cowork #204, caff989)
        logger.debug("fusion_core absent — client key falls back to FUSION_CLIENT_KEY")
        return os.environ.get("FUSION_CLIENT_KEY", "")
    return client_key()


def service_listen_port(legacy_default: int) -> int:
    # 监听端口经 fusion_core.service_port 单点解析: FUSION_K12_TEACHER_PORT
    # 优先, 未设时回退 legacy FUSION_K12_PORT / 内置默认 — 旧部署零改动。
    try:
        from fusion_core.config import service_port
    except ImportError:
        logger.debug("fusion_core absent — port falls back to FUSION_K12_PORT")
        return int(os.environ.get("FUSION_K12_PORT", str(legacy_default)))
    return service_port("fusion-k12-teacher", default=_legacy_port_env(legacy_default))


def _legacy_port_env(legacy_default: int) -> int:
    raw = os.environ.get("FUSION_K12_PORT", "")
    if not raw:
        return legacy_default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid env FUSION_K12_PORT=%s: not an integer, using %s", raw, legacy_default)
        return legacy_default
