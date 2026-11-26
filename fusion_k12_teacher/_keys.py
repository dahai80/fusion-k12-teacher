# #34 (config Phase 2.2): Single-point resolution of gateway credentials.
#
# config-conventions §1/§2: the only implementation lives in fusion_core.config —
# repos must not copy the parsing logic locally. fusion_core is an optional
# dependency (.[core]); when absent, fall back to semantically equivalent legacy
# env reads so isolated environments do not regress.

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def gateway_client_key() -> str:
    # Canonical name FUSION_CLIENT_KEY (alias chain lives in fusion_core); dev
    # default empty + warning, FUSION_PROFILE=prod default RuntimeError — see
    # fusion_core.config for semantics.
    try:
        from fusion_core.config import client_key
    except ImportError:
        # issue #35: bare-install fallback only honors canonical FUSION_CLIENT_KEY
        # — the alias chain lives only in fusion_core, this repo does not
        # duplicate it (pattern: fusion-cowork #204, caff989)
        logger.debug("fusion_core absent — client key falls back to FUSION_CLIENT_KEY")
        return os.environ.get("FUSION_CLIENT_KEY", "")
    return client_key()


def service_listen_port(legacy_default: int) -> int:
    # Listen port resolved at the single point fusion_core.service_port:
    # FUSION_K12_TEACHER_PORT takes priority, falls back to legacy
    # FUSION_K12_PORT / built-in default — zero change for old deployments.
    try:
        from fusion_core.config import service_port
    except ImportError:
        logger.debug("fusion_core absent — port falls back to FUSION_K12_PORT")
        return _legacy_port_env(legacy_default)
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
