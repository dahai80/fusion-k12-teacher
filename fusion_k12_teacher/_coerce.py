"""from_dict 统一类型强转 (E13)。

原各模块 from_dict 强转策略分叉: analytics 有 _coerce_* 防御, agent/desensitize/safety
裸 d.get 不强转, LLM 返回畸形类型时强转字段静默吞错、未强转抛 TypeError。此处收敛为
单实现, 所有 from_dict 经此守门, 行为可预测。
"""

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
