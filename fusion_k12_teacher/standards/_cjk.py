from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# i18n: user-facing (CJK character-range data, functional)
_CJK_RE = re.compile(r"[一-鿿]")


def _cjk_tokens(text: str) -> list[str]:
    """CJK+Latin mixed tokenization — CJK segments take 2-grams, Latin segments
    split on whitespace (STD-6/7).

    E4: single implementation, shared by query.py and aligner.py (previously
    two copied versions had diverged).
    STD-2: a single-char CJK chunk produces 0 bigrams (empty range(0)); the
    fallback keeps the original chunk instead of dropping it, avoiding an
    always-false empty token set that would miss all alignments.
    """
    text = text.lower().strip()
    tokens: list[str] = []
    for chunk in text.split():
        if _CJK_RE.search(chunk):
            tokens.extend(chunk[i:i + 2] for i in range(len(chunk) - 1))
            tokens.append(chunk)
        else:
            tokens.append(chunk)
    return [t for t in tokens if t]


def _word_match(needle: str, haystack: str) -> bool:
    """CJK whole-word match — bigram token intersection instead of raw substring,
    avoiding a short term (e.g. a 2-char topic word) matching inside an unrelated
    longer phrase that merely contains the same characters.

    Both needle and haystack are bigram-tokenized; a hit requires at least 1
    needle bigram to appear in the haystack token set.
    Latin words use exact token equality. When no bigram exists (needle < 2
    chars), fall back to raw substring (already gated by loose matching).
    E4: single implementation, shared by query.py and aligner.py.
    """
    if not needle:
        return False
    if len(needle) < 2:
        return needle in haystack
    hay_set = set(_cjk_tokens(haystack))
    return any(tok in hay_set for tok in _cjk_tokens(needle))
