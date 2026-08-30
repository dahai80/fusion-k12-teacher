"""Prompt 构建层 — 统一 sanitize 守门 (E12)。

原各引擎 prompt 用 f-string 手拼, sanitize_input 逐字段手调, 漏 sanitize 即注入面,
且无模板系统使 prompt 变更无审计/版本。此处提供 build_prompt: 调用方传模板字符串
+ 变量字典, build_prompt 对所有字符串变量统一过 sanitize_input, 再 format 注入,
杜绝"新增字段忘 sanitize"。

用法:
    prompt = build_prompt(
        "学科: {subject}\\n年级: {grade}\\n主题: {topic}",
        subject="数学", grade="3", topic="分数",
    )

非字符串变量(int/float/已渲染列表)原样注入, 不经 sanitize (非用户可控文本)。
需要单独 max_len 的字段, 在 vals 中传已 sanitize 的值即可绕过二次处理。
"""

from __future__ import annotations

import logging
from typing import Any

from .safety.filter import sanitize_input

logger = logging.getLogger(__name__)

_DEFAULT_MAX_LEN = 500


def build_prompt(template: str, **vals: Any) -> str:
    """E12: 统一 sanitize 的 prompt 构建 — 所有字符串变量自动过 sanitize_input。

    template 须用 {name} 占位 (str.format 风格, 花括号字面量用 {{ }} 转义)。
    字符串 vals 经 sanitize_input(防注入/截断/控字符剥离), 非字符串原样注入。
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
        # 模板占位与 vals 不匹配 — 诚实报错, 不静默返回半截 prompt
        logger.error("prompt 模板占位与变量不匹配: %s | template: %s", e, template[:120])
        raise
