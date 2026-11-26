"""issue #22: BNUP Socratic teaching prompt registry — centrally manages the 8
primitive routes + system instructions."""

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
