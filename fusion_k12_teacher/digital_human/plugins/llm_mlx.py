"""MlxLLM — fusion-mlx /v1/chat/completions stream 插件。

课程上下文由 ContentInjector 注入 system prompt。SSE token 流。
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from .base import LLMPlugin

logger = logging.getLogger(__name__)


class MlxLLM(LLMPlugin):
    name = "mlx_llm"

    def __init__(self, mlx_client: Any, *, temperature: float = 0.6, max_tokens: int = 1024) -> None:
        self._mlx = mlx_client
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._available = False
        self._cancelled = False

    @property
    def available(self) -> bool:
        return self._available

    async def init(self) -> None:
        if self._mlx is None:
            logger.warning("llm_mlx: mlx_client 为 None, 不可用")
            self._available = False
            return
        self._available = True
        logger.info("llm_mlx: init")

    async def stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        if not self._available:
            yield ""
            return
        self._cancelled = False
        try:
            resp = await self._mlx.chat_stream(
                messages, temperature=self._temperature, max_tokens=self._max_tokens,
            )
            async with resp as response:
                async for line in response.aiter_lines():
                    if self._cancelled:
                        logger.info("llm_mlx: 流被中断")
                        break
                    line = line.strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                        delta = obj.get("choices", [{}])[0].get("delta", {}).get("content", "")
                        if delta:
                            yield delta
                    except (json.JSONDecodeError, IndexError, KeyError) as exc:
                        logger.debug("llm_mlx: 跳过非 SSE 行 %s", type(exc).__name__)
        except Exception as exc:
            logger.error("llm_mlx: 流失败 %s", exc)
            yield ""

    async def cancel(self) -> None:
        self._cancelled = True

    def clear(self) -> None:
        self._cancelled = False

    async def close(self) -> None:
        pass
