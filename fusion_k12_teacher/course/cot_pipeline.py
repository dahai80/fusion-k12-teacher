# issue #20: two-stage CoT pipeline — <thinking> free reasoning → <dsl>
# constrained JSON.
#
# Two-stage strategy (gateway#184 already supports GBNF grammar passthrough):
#   Stage 1: enable_thinking=True streaming reasoning, produces a free thinking chain
#   Stage 2: based on the thinking chain context, produces structured DSL JSON
#   (can be constrained by a GBNF grammar)
#
# This module provides:
#   - cot_enabled(): reads the FUSION_K12_COT_ENABLED env var
#   - stream_thinking(): streams thinking tokens with per-chunk callbacks
#   - extract_thinking(): isolates thinking vs body from mixed output
#   - extract_dsl(): extracts JSON inside <dsl> tags from mixed output (issue #20 gap 1)
#   - DSL_GBNF_GRAMMAR: GBNF grammar, passed through via chat_stream(grammar=) (issue #20 gap 2)
#   - COT_THINKING_PROMPT / COT_DSL_PROMPT: two-stage prompt templates

from __future__ import annotations

import logging
import os
import re
from collections.abc import AsyncIterator, Callable
from typing import Any

from .prompts.bnup_socratic import BNUP_COT_FORMAT_PROMPT, BNUP_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


# issue #20: whether two-stage CoT is enabled — env FUSION_K12_COT_ENABLED=true.
def cot_enabled() -> bool:
    return os.environ.get("FUSION_K12_COT_ENABLED", "").lower() in ("1", "true", "yes", "on")


_THINK_PATTERN = re.compile(r"<(?:think|thinking)>(.*?)</(?:think|thinking)>", re.DOTALL | re.IGNORECASE)
_THINK_OPEN = re.compile(r"<(?:think|thinking)>", re.IGNORECASE)
_THINK_CLOSE = re.compile(r"</(?:think|thinking)>", re.IGNORECASE)

_DSL_PATTERN = re.compile(r"<dsl>(.*?)</dsl>", re.DOTALL | re.IGNORECASE)
_DSL_OPEN = re.compile(r"<dsl>", re.IGNORECASE)
_DSL_CLOSE = re.compile(r"</dsl>", re.IGNORECASE)


# Isolate thinking vs body text from model output.
#
#     Returns (thinking_text, content_text).
#     Qwen3 thinking mode outputs a <thinking>...</thinking> block + body text.
def extract_thinking(raw: str) -> tuple[str, str]:
    if not raw:
        return "", ""
    matches = _THINK_PATTERN.findall(raw)
    thinking = "\n".join(m.strip() for m in matches if m.strip())
    content = _THINK_PATTERN.sub("", raw).strip()
    if not thinking:
        open_match = _THINK_OPEN.search(raw)
        if open_match:
            rest = raw[open_match.end():]
            close_match = _THINK_CLOSE.search(rest)
            if close_match:
                thinking = rest[:close_match.start()].strip()
                content = (rest[close_match.end():] + raw[:open_match.start()]).strip()
            else:
                thinking = rest.strip()
                content = raw[:open_match.start()].strip()
    logger.info("extract_thinking: thinking=%d chars content=%d chars", len(thinking), len(content))
    return thinking, content


# issue #20 gap 1: extract JSON inside <dsl> tags from mixed output.
#
#     Model two-stage output: <thinking>reasoning</thinking> + <dsl>{"steps":[...]}</dsl>.
#     Extracts the dsl tag content, trimming surrounding whitespace. When no tag
#     is present, tries to find a JSON block in the body.
#     Returns the dsl_json string or None.
def extract_dsl(raw: str) -> str | None:
    if not raw:
        return None
    matches = _DSL_PATTERN.findall(raw)
    if matches:
        dsl_text = matches[0].strip()
        logger.info("extract_dsl: found <dsl> tag (%d matches), %d chars", len(matches), len(dsl_text))
        return dsl_text
    open_match = _DSL_OPEN.search(raw)
    if open_match:
        rest = raw[open_match.end():]
        close_match = _DSL_CLOSE.search(rest)
        if close_match:
            dsl_text = rest[:close_match.start()].strip()
            logger.info("extract_dsl: found open/close tag, %d chars", len(dsl_text))
            return dsl_text
        logger.warning("extract_dsl: <dsl> open tag but no close, take rest")
        return rest.strip()
    content = _THINK_PATTERN.sub("", raw).strip()
    if content.startswith("{") and content.endswith("}"):
        logger.info("extract_dsl: no <dsl> tag, content looks like JSON (%d chars)", len(content))
        return content
    from .._parse import parse_json
    parsed = parse_json(content)
    if parsed:
        import json
        dsl_text = json.dumps(parsed, ensure_ascii=False)
        logger.info("extract_dsl: no <dsl> tag, extracted JSON via parse_json (%d chars)", len(dsl_text))
        return dsl_text
    logger.warning("extract_dsl: no <dsl> tag and no JSON found in %d chars", len(raw))
    return None


# issue #20 gap 2: GBNF grammar for constraining DSL JSON output.
# gateway#184 passes grammar param through to mlx; this constrains stage-2
# output to valid JSON structure, eliminating parse failures.
DSL_GBNF_GRAMMAR = r"""root ::= "{" "\"meta\"" ":" meta "," "\"global_variables\"" ":" gv "," "\"steps\"" ":" "[" steps "]" "}"
meta ::= "{" "\"visual_type\"" ":" string "," "\"fallback_type\"" ":" string "}"
gv ::= "{" "}" | "{" string ":" gv_entry ("," string ":" gv_entry)* "}"
gv_entry ::= "{" "\"label\"" ":" string "," "\"unit\"" ":" string "," "\"value\"" ":" number "," "\"is_unknown\"" ":" bool "}"
steps ::= step | step "," steps
step ::= "{" "\"step_id\"" ":" string "," "\"step_title\"" ":" string "," "\"phase\"" ":" string "," "\"speech_narration\"" ":" string "," "\"checkpoint\"" ":" cp "}"
cp ::= "null" | "{" "\"id\"" ":" string "," "\"type\"" ":" string "," "\"prompt\"" ":" string "}"
string ::= "\"" ([^"\\] | "\\" .)* "\""
number ::= ("-"? [0-9]+ ("." [0-9]+)?) | "null"
bool ::= "true" | "false"
"""


# i18n: user-facing — LLM prompt template (product content), keep Chinese.
COT_THINKING_PROMPT = BNUP_SYSTEM_PROMPT + "\n" + BNUP_COT_FORMAT_PROMPT + """

请深度分析以下课题的教学路径, 自由推理。

课题: {topic} (年级 {grade})
知识点节点: {node_id}
前置知识: {prerequisites}
易错点: {misconceptions}

请分析:
1. 学生的认知起点与已有经验
2. 本课题的核心数学思想与关键概念
3. 可能的学习障碍与易错点成因
4. 5E 各阶段 (Engage/Explore/Explain/Elaborate/Evaluate) 的教学策略
5. 可视化呈现方式选择依据 (8 基元之一)
6. checkpoint 设计意图 (苏格拉底式不直接给答案)

自由推理, 不需要格式化输出。"""

# i18n: user-facing — LLM prompt template (product content), keep Chinese.
COT_DSL_PROMPT = """基于以上教学分析, 生成结构化课稿 DSL JSON。

课题: {topic} (年级 {grade})
可视化类型: {visual_type}

要求:
- 严格分 3-5 步, 每步属于一个 5E 阶段。
- 每步含 speech_narration + animation + visual_state + checkpoint。
- meta.visual_type 从 8 基元选一, meta.fallback_type 从 2 兜底选一。
- checkpoint 不直接给答案, 用 hints 分级提示。

用 <dsl> 标签包裹 JSON 输出, 格式: <dsl>{...}</dsl>
只输出 <dsl> 标签及其内容, 不输出其他文字。"""


# issue #20: stream thinking tokens with per-chunk on_chunk callbacks
#     (supports sync/async callbacks).
#
#     Returns the full thinking text. Returns an empty string on error
#     (degrade, do not block DSL generation).
async def stream_thinking(
    mlx: Any,
    messages: list[dict[str, str]],
    *,
    on_chunk: Callable[[str], Any] | None = None,
    temperature: float = 0.5,
    max_tokens: int = 2048,
) -> str:
    import inspect
    try:
        resp = await mlx.chat_stream(
            messages, temperature=temperature, max_tokens=max_tokens,
            enable_thinking=True,
        )
        full_text: list[str] = []
        async with resp as stream:
            async for line in stream.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:].strip()
                if data == "[DONE]":
                    break
                try:
                    import json
                    chunk = json.loads(data)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    token = delta.get("reasoning_content") or delta.get("content") or ""
                    if token:
                        full_text.append(token)
                        if on_chunk:
                            result = on_chunk(token)
                            if inspect.isawaitable(result):
                                await result
                except Exception:
                    continue
        thinking = "".join(full_text)
        logger.info("stream_thinking: got %d chars", len(thinking))
        return thinking
    except Exception as exc:
        logger.warning("stream_thinking failed (degraded): %s", exc)
        return ""


# Yield tokens one by one from a chat_stream httpx Response
#     (content + reasoning_content).
async def iter_sse_tokens(resp: Any) -> AsyncIterator[str]:
    async with resp as stream:
        async for line in stream.aiter_lines():
            if not line.startswith("data: "):
                continue
            data = line[6:].strip()
            if data == "[DONE]":
                break
            try:
                import json
                chunk = json.loads(data)
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                token = delta.get("reasoning_content") or delta.get("content") or ""
                if token:
                    yield token
            except Exception:
                continue
