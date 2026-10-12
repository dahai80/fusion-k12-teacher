"""issue #20: 两阶段 CoT pipeline — <thinking> 自由推理 → <dsl> 约束 JSON。

两阶段策略 (gateway#184 已支持 GBNF grammar 透传):
  阶段 1: enable_thinking=True 流式推理, 产出 thinking 自由思考链
  阶段 2: 基于思考链上下文, 产出结构化 DSL JSON (可用 GBNF grammar 约束)

本模块提供:
  - cot_enabled(): 读 FUSION_K12_COT_ENABLED 环境变量
  - stream_thinking(): 流式获取 thinking tokens, 逐块回调
  - extract_thinking(): 从混合输出中隔离 thinking 与正文
  - extract_dsl(): 从混合输出中提取 <dsl> 标签内 JSON (issue #20 gap 1)
  - DSL_GBNF_GRAMMAR: GBNF 语法, 经 chat_stream(grammar=) 透传 (issue #20 gap 2)
  - COT_THINKING_PROMPT / COT_DSL_PROMPT: 两阶段 prompt 模板
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import AsyncIterator, Callable
from typing import Any

from .prompts.bnup_socratic import BNUP_COT_FORMAT_PROMPT, BNUP_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


def cot_enabled() -> bool:
    """issue #20: 两阶段 CoT 是否启用 — env FUSION_K12_COT_ENABLED=true。"""
    return os.environ.get("FUSION_K12_COT_ENABLED", "").lower() in ("1", "true", "yes", "on")


_THINK_PATTERN = re.compile(r"<(?:think|thinking)>(.*?)</(?:think|thinking)>", re.DOTALL | re.IGNORECASE)
_THINK_OPEN = re.compile(r"<(?:think|thinking)>", re.IGNORECASE)
_THINK_CLOSE = re.compile(r"</(?:think|thinking)>", re.IGNORECASE)

_DSL_PATTERN = re.compile(r"<dsl>(.*?)</dsl>", re.DOTALL | re.IGNORECASE)
_DSL_OPEN = re.compile(r"<dsl>", re.IGNORECASE)
_DSL_CLOSE = re.compile(r"</dsl>", re.IGNORECASE)


def extract_thinking(raw: str) -> tuple[str, str]:
    """从模型输出中隔离 thinking 与正文。

    返回 (thinking_text, content_text)。
    Qwen3 thinking 模式输出 <thinking>...</thinking> 块 + 正文。
    """
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


def extract_dsl(raw: str) -> str | None:
    """issue #20 gap 1: 从混合输出中提取 <dsl> 标签内 JSON。

    模型两阶段输出: <thinking>推理</thinking> + <dsl>{"steps":[...]}</dsl>。
    提取 dsl 标签内容, 去除前后空白。无标签时尝试从正文找 JSON 块。
    返回 dsl_json 字符串或 None。
    """
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


async def stream_thinking(
    mlx: Any,
    messages: list[dict[str, str]],
    *,
    on_chunk: Callable[[str], Any] | None = None,
    temperature: float = 0.5,
    max_tokens: int = 2048,
) -> str:
    """issue #20: 流式获取 thinking tokens, 逐块回调 on_chunk (支持 sync/async 回调)。

    返回完整 thinking 文本。出错返回空字符串 (降级, 不阻断 DSL 生成)。
    """
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
        logger.warning("stream_thinking 失败 (降级): %s", exc)
        return ""


async def iter_sse_tokens(resp: Any) -> AsyncIterator[str]:
    """从 chat_stream 的 httpx Response 中逐 token 产出 (content + reasoning_content)。"""
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
