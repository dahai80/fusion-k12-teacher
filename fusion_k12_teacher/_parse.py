"""LLM JSON 解析 — 单一实现 (E1)。

原 7 引擎各抄一份 _parse_json, 已分叉两种实现 (split-based / regex-based),
CLAUDE.md 标注"intentional per-module isolation"掩盖了 DRY 违反与副本漂移。
此处收敛为单一实现, 各引擎导入此函数, 杜绝一处改忘别处。

实现取 analytics 的平衡括号扫描 (最稳健, 不被多对象文本跨界抓取),
辅以 ```json``` 围栏提取与有界长度保护。
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
    """平衡括号扫描, 取首个完整 JSON 对象/数组。
    贪婪正则 \{.*\} 在多对象文本会跨界抓到无效串, 此法按括号深度精确截取。"""
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
    """解析 LLM 返回的 JSON — 容忍 None/空串/代码块围栏/超长 (ENG-5/6/7/20)。

    E1: 单一实现, 各引擎导入。返回 dict/list 或 None (解析失败)。
    """
    if not isinstance(text, str) or not text.strip():
        return None
    if len(text) > _MAX_PARSE_LEN:
        logger.warning("LLM 返回过长(%d 字符), 截断后再解析", len(text))
        text = text[:_MAX_PARSE_LEN]
    text = text.strip()
    # 优先取 ```json``` 代码块, 否则平衡括号扫描取首个完整 JSON
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
