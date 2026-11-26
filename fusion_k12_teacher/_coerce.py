# Unified from_dict type coercion (E13).
#
# Previously each module's from_dict coercion strategy diverged: analytics had
# _coerce_* defenses while agent/desensitize/safety used bare d.get with no
# coercion — malformed LLM types were silently swallowed on coerced fields but
# raised TypeError on uncoerced ones. Consolidated here into a single
# implementation; all from_dict paths go through this gate with predictable
# behavior.

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def coerce_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def coerce_int(val: Any, default: int = 0) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        try:
            return int(float(val))
        except (TypeError, ValueError):
            return default


def coerce_str(val: Any) -> str:
    if val is None:
        return ""
    return str(val)


def coerce_bool(val: Any, default: bool = True) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    if isinstance(val, str):
        s = val.strip().lower()
        if s in ("true", "1", "yes", "y", "on"):
            return True
        if s in ("false", "0", "no", "n", "off", ""):
            return False
    return default


def coerce_str_list(val: Any) -> list[str]:
    if isinstance(val, list):
        return [str(x) for x in val]
    if isinstance(val, str):
        return [val]
    return []


def coerce_str_dict(val: Any) -> dict[str, float]:
    if not isinstance(val, dict):
        return {}
    out: dict[str, float] = {}
    for k, v in val.items():
        try:
            out[str(k)] = float(v)
        except (TypeError, ValueError):
            out[str(k)] = 0.0
    return out


def coerce_dict_list(val: Any) -> list[dict[str, Any]]:
    if not isinstance(val, list):
        return []
    return [x for x in val if isinstance(x, dict)]


def coerce_dict(val: Any) -> dict[str, Any]:
    if not isinstance(val, dict):
        return {}
    return val
