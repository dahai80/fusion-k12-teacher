"""Prompt building layer — unified sanitize gate (E12).

Engines used to hand-assemble prompts with f-strings and call sanitize_input field by field;
a missed sanitize is an injection surface, and with no template system prompt changes had
no audit/version trail. This module provides build_prompt: the caller passes a template
string + a variable dict; build_prompt runs every string variable through sanitize_input
uniformly, then format-injects, eliminating "forgot to sanitize the new field".

Usage:
    prompt = build_prompt(
        "Subject: {subject}\\nGrade: {grade}\\nTopic: {topic}",
        subject="math", grade="3", topic="fractions",
    )

Non-string variables (int/float/pre-rendered lists) are injected as-is, without sanitize
(not user-controlled text). Fields needing a custom max_len can pass pre-sanitized values
in vals to skip the second pass.
"""

from __future__ import annotations

import logging
from typing import Any

from .safety.filter import sanitize_input

logger = logging.getLogger(__name__)

_DEFAULT_MAX_LEN = 500


def build_prompt(template: str, **vals: Any) -> str:
    """E12: prompt building with unified sanitize — all string variables run through sanitize_input automatically.

    template must use {name} placeholders (str.format style, literal braces escaped as {{ }}).
    String vals go through sanitize_input (injection defense/truncation/control-char stripping);
    non-strings are injected as-is.
    """
    safe_vals: dict[str, Any] = {}
    for k, v in vals.items():
        if isinstance(v, str):
            safe_vals[k] = sanitize_input(v, _DEFAULT_MAX_LEN)
        else:
            safe_vals[k] = v
    try:
        return template.format(**safe_vals)
    except (KeyError, IndexError) as e:
        # Template placeholders do not match vals — fail honestly, never return a half-built prompt silently
        logger.error("prompt template placeholder does not match variables: %s | template: %s", e, template[:120])
        raise
