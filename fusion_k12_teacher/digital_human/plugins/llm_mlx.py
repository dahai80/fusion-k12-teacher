"""MlxLLM — fusion-mlx /v1/chat/completions stream 插件。

课程上下文由 ContentInjector 注入 system prompt。SSE token 流。
"""

from __future__ import annotations

import json
import logging
import os
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

    async def describe_image(self, image_b64: str, question: str = "") -> str:
        """图片提问 (模式3): Qwen2.5-VL 看图 → 文字描述, 结果并入答疑上下文。

        VLM 模型可配 FUSION_K12_VLM_MODEL; 不存在/失败返空串 (降级纯文字答疑)。
        """
        if not self._available or not image_b64:
            return ""
        model = os.environ.get("FUSION_K12_VLM_MODEL", "mlx-community--Qwen2.5-VL-7B-Instruct-4bit")
        content = [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
            {"type": "text", "text": question or "请描述这张图片的内容，若是题目请抄出题目"},
        ]
        try:
            desc = await self._mlx.chat(
                [{"role": "user", "content": content}], temperature=0.3, max_tokens=512, model=model,
            )
            logger.info("llm_mlx: VLM 看图完成 %d 字节描述", len(desc or ""))
            return (desc or "").strip()
        except Exception as exc:
            logger.warning("llm_mlx: VLM 看图失败 (降级纯文字): %s", exc)
            return ""

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
