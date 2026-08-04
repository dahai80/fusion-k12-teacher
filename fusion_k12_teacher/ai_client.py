"""Fusion-K12-Teacher AI 客户端 — 所有 AI 推理的唯一接口。

All LLM calls go through fusion-mlx's OpenAI-compatible HTTP API.
This is a thin wrapper around fusion-core's FusionMLXClient.
No direct mlx or mlx-lm imports — every call is routed via fusion-mlx.
"""

from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional

from fusion_core.mlx_client import FusionMLXClient as _FusionMLXClient

logger = logging.getLogger(__name__)

DEFAULT_MLX_BASE_URL = os.environ.get(
    "FUSION_MLX_URL", "http://localhost:11432/v1"
)


class MLXClient:
    """fusion-mlx HTTP 客户端 — 所有 AI 推理的唯一接口。

    Thin wrapper around fusion-core's FusionMLXClient.
    All LLM calls go through fusion-mlx's /v1/chat/completions endpoint.
    Default base_url: http://localhost:11432/v1 (overridable via FUSION_MLX_URL env).
    """

    def __init__(self, model: str = "", base_url: str = ""):
        url = base_url or DEFAULT_MLX_BASE_URL
        self.model = model
        self._inner = _FusionMLXClient(base_url=url)

    async def chat(self, messages: List[Dict[str, str]], temperature: float = 0.7, max_tokens: int = 4096) -> str:
        """Call fusion-mlx /v1/chat/completions — all LLM inference goes through fusion-mlx."""
        if not self.model:
            try:
                models = await self._inner.list_models()
                if models:
                    self.model = models[0].get("id", models[0].get("model", ""))
            except Exception:
                self.model = "qwen3.5-9b"
        return await self._inner.chat_text(
            model=self.model or "qwen3.5-9b",
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )