"""Chinese speech-text normalization — TTS pre-processing (issue: Kokoro's Chinese G2P is weak on number normalization).

K12 classroom content is full of fractions/decimals/percent signs/math symbols; Kokoro synthesizes
them with skipped or wrong readings. This module rewrites such fragments into Chinese spoken form —
pure functions, no dependencies, called by TTS plugins.
Coverage is deliberately conservative: only deterministic rules are rewritten, no full Chinese-number
conversion for arbitrary numbers (multi-digit/year/phone contexts are too ambiguous — left to the TTS engine).
"""

from __future__ import annotations

import re

# i18n: user-facing (math symbol → Chinese reading map, functional TTS data)
_SYMBOL_MAP = {
    "π": "派",
    "≈": "约等于",
    "≠": "不等于",
    "≤": "小于等于",
    "≥": "大于等于",
    "×": "乘以",
    "÷": "除以",
    "±": "正负",
    "°C": "摄氏度",
    "℃": "摄氏度",
}

# i18n: user-facing (Chinese digit readings, functional TTS data)
_CN_DIGITS = "零一二三四五六七八九"


def _int_to_cn(n: int) -> str:
    """Converts integers 0-99 to Chinese readings (sufficient for fraction/percent scenarios)."""
    if n < 0 or n > 99:
        return str(n)
    if n <= 10:
        return _CN_DIGITS[n] if n < 10 else "十"
    tens, ones = divmod(n, 10)
    prefix = "" if tens == 1 else _CN_DIGITS[tens]
    return f"{prefix}十" + (_CN_DIGITS[ones] if ones else "")


def _frac_repl(m: re.Match) -> str:
    # i18n: user-facing (Chinese fraction reading: 3/4 → 四分之三, denominator first)
    a, b = int(m.group(1)), int(m.group(2))
    if b == 0:
        return m.group(0)
    b_cn = _int_to_cn(b)
    if b_cn == str(b) or _int_to_cn(a) == str(a):  # numerator or denominator outside 0-99, give up rewriting
        return m.group(0)
    return f"{b_cn}分之{_int_to_cn(a)}"


def _percent_repl(m: re.Match) -> str:
    # i18n: user-facing (Chinese percent reading)
    n = int(m.group(1))
    n_cn = _int_to_cn(n)
    if n_cn == str(n):  # outside 0-99, give up rewriting
        return m.group(0)
    return f"百分之{n_cn}"


def _decimal_repl(m: re.Match) -> str:
    # i18n: user-facing (decimal: integer part plus per-digit reading, 3.14 → 三点一四)
    int_part, dec_part = m.group(1), m.group(2)
    int_cn = _int_to_cn(int(int_part)) if int_part.isdigit() and len(int_part) <= 2 else int_part
    dec_cn = "".join(_CN_DIGITS[int(d)] for d in dec_part if d.isdigit())
    return f"{int_cn}点{dec_cn}"


def normalize_zh_speech(text: str) -> str:
    """Rewrites common K12 math notations into Chinese spoken form — all other text returned as-is."""
    if not text:
        return text
    out = text
    for sym, reading in _SYMBOL_MAP.items():
        out = out.replace(sym, reading)
    # Fraction a/b (integers; simple no-space integer form avoids mangling URLs/paths)
    out = re.sub(r"(?<![\d./])(\d{1,3})/(\d{1,3})(?![\d./])", _frac_repl, out)
    # Percent: 56% → 百分之五十六 (integers; decimal percents conservatively skipped)
    out = re.sub(r"(?<![\d.])(\d{1,3})%(?![\d%])", _percent_repl, out)
    # Decimal: 3.14 → 三点一四 (pure numeric form only)
    out = re.sub(r"(?<![\d.])(\d{1,3})\.(\d{1,6})(?![\d.])", _decimal_repl, out)
    return out
