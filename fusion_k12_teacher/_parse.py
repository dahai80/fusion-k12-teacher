"""LLM JSON parsing — single implementation (E1).

The 7 engines used to each carry a copy of _parse_json, already diverged into two
implementations (split-based / regex-based); the CLAUDE.md note "intentional per-module
isolation" masked the DRY violation and copy drift. Consolidated here into a single
implementation imported by all engines, eliminating fix-here-forget-there.

Implementation uses analytics' balanced-brace scan (most robust, not fooled by multiple
objects across text boundaries), plus ```json``` fence extraction and bounded length protection.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_MAX_PARSE_LEN = 200000
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _extract_first_json(text: str) -> str:
    """Balanced-brace scan, returns the first complete JSON object/array.
    The greedy regex \{.*\} crosses object boundaries in multi-object text and grabs invalid
    spans; this method slices precisely by brace depth."""
    start = -1
    close_ch = ""
    depth = 0
    in_str = False
    escape = False
    for i, c in enumerate(text):
        if in_str:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
            continue
        if c in "{[":
            if depth == 0:
                start = i
                close_ch = "}" if c == "{" else "]"
            depth += 1
        elif c in "}]":
            if depth > 0:
                depth -= 1
                if depth == 0 and start >= 0 and c == close_ch:
                    return text[start : i + 1]
    return ""


def parse_json(text: Any) -> Any:
    """Parse JSON returned by the LLM — tolerates None/empty/code fences/overlong input (ENG-5/6/7/20).

    E1: single implementation, imported by all engines. Returns dict/list or None (parse failure).
    """
    if not isinstance(text, str) or not text.strip():
        return None
    if len(text) > _MAX_PARSE_LEN:
        logger.warning("LLM response too long (%d chars), truncating before parse", len(text))
        text = text[:_MAX_PARSE_LEN]
    text = text.strip()
    # Prefer the ```json``` code block, otherwise balanced-brace scan takes the first complete JSON
    match = _FENCE_RE.search(text)
    if match:
        candidate = match.group(1).strip()
    else:
        candidate = _extract_first_json(text)
    if not candidate:
        return None
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None
