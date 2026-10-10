"""issue #22: BNUP 苏格拉底教学 prompt 注册表 — 集中管理 8 基元路由 + 系统指令。"""

from .bnup_socratic import (
    BNUP_COT_FORMAT_PROMPT,
    BNUP_SYSTEM_PROMPT,
    BNUP_VISUAL_ROUTING_PROMPT,
    FALLBACK_VISUAL,
    VISUAL_ROUTING_RULES,
    build_bnup_prompt,
    route_visual_type,
)

__all__ = [
    "BNUP_COT_FORMAT_PROMPT",
    "BNUP_SYSTEM_PROMPT",
    "BNUP_VISUAL_ROUTING_PROMPT",
    "FALLBACK_VISUAL",
    "VISUAL_ROUTING_RULES",
    "build_bnup_prompt",
    "route_visual_type",
]
