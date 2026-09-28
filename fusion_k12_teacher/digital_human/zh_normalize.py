"""中文朗读文本规范化 — TTS 前置处理 (issue: Kokoro 中文 G2P 数字规范化弱)。

K12 课堂内容大量出现分数/小数/百分号/数学符号, Kokoro 直接合成会跳读或读错。
本模块把这类片段改写成中文朗读形式, 纯函数、无依赖, 供 TTS 插件调用。
覆盖范围刻意保守: 只改写确定性规则, 不做任意数字的完整中文读法转换
(多位数/年份/电话号码等语境歧义大, 交由 TTS 引擎处理)。
"""

from __future__ import annotations

import re

# 数学符号 → 中文读法
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

# 整数 0-20 及整十 → 中文 (用于分数/百分号内联转换)
_CN_DIGITS = "零一二三四五六七八九"


def _int_to_cn(n: int) -> str:
    """0-99 整数转中文读法 (分数/百分号场景足够)。"""
    if n < 0 or n > 99:
        return str(n)
    if n <= 10:
        return _CN_DIGITS[n] if n < 10 else "十"
    tens, ones = divmod(n, 10)
    prefix = "" if tens == 1 else _CN_DIGITS[tens]
    return f"{prefix}十" + (_CN_DIGITS[ones] if ones else "")


def _frac_repl(m: re.Match) -> str:
    # 中文分数读法: 3/4 → 四分之三 (分母在前)
    a, b = int(m.group(1)), int(m.group(2))
    if b == 0:
        return m.group(0)
    b_cn = _int_to_cn(b)
    if b_cn == str(b) or _int_to_cn(a) == str(a):  # 分子或分母超 0-99, 放弃改写
        return m.group(0)
    return f"{b_cn}分之{_int_to_cn(a)}"


def _percent_repl(m: re.Match) -> str:
    n = int(m.group(1))
    n_cn = _int_to_cn(n)
    if n_cn == str(n):  # 超 0-99, 放弃改写
        return m.group(0)
    return f"百分之{n_cn}"


def _decimal_repl(m: re.Match) -> str:
    # 小数: 整数部分与各位数字逐位读 (3.14 → 三点一四)
    int_part, dec_part = m.group(1), m.group(2)
    int_cn = _int_to_cn(int(int_part)) if int_part.isdigit() and len(int_part) <= 2 else int_part
    dec_cn = "".join(_CN_DIGITS[int(d)] for d in dec_part if d.isdigit())
    return f"{int_cn}点{dec_cn}"


def normalize_zh_speech(text: str) -> str:
    """把 K12 常见数学写法改写为中文朗读形式 — 其余文本原样返回。"""
    if not text:
        return text
    out = text
    for sym, reading in _SYMBOL_MAP.items():
        out = out.replace(sym, reading)
    # 分数 a/b (整数, 读写入交替时避免误伤 URL/路径 — 不带空格的简单整数形态)
    out = re.sub(r"(?<![\d./])(\d{1,3})/(\d{1,3})(?![\d./])", _frac_repl, out)
    # 百分号: 56% → 百分之五十六 (整数; 小数百分号保守跳过)
    out = re.sub(r"(?<![\d.])(\d{1,3})%(?![\d%])", _percent_repl, out)
    # 小数: 3.14 → 三点一四 (仅纯数字形态)
    out = re.sub(r"(?<![\d.])(\d{1,3})\.(\d{1,6})(?![\d.])", _decimal_repl, out)
    return out
