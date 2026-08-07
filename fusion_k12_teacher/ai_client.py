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
DEFAULT_MODEL = os.environ.get("FUSION_MLX_MODEL", "Qwen3.5-9B-4bit")

# 自动选择时的优先聊天模型候选（按优先级）
_PREFERRED_CHAT_MODELS = (
    "Qwen3.5-9B-4bit", "Qwen3.5-9B", "Qwen3.5-4B", "Qwen3-4B",
    "Qwen3.5-4B-bf16", "Qwen3.5-4B-4bit", "Qwen3-0.6B",
)
# 非聊天模型关键词（扩散/嵌入/TTS/视觉编码器等）
_NON_CHAT_KEYWORDS = (
    "dit", "vae", "text_encoder", "transformer", "embed", "bge",
    "siglip", "tts", "sdxl", "flux", "wan", "ltx", "skyreels",
    "pangu-embedded", "eagle3", "oldt5", "diffusion", "clip",
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
            self.model = await self._auto_select_model()
        return await self._inner.chat_text(
            model=self.model or "qwen3.5-9b",
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    async def _auto_select_model(self) -> str:
        """自动选择可用聊天模型 — 优先匹配已知聊天模型，跳过非聊天模型。"""
        try:
            models = await self._inner.list_models()
        except Exception:
            logger.warning("list_models 失败，回退默认模型 %s", DEFAULT_MODEL)
            return DEFAULT_MODEL
        if not models:
            return DEFAULT_MODEL
        ids = {m.get("id", m.get("model", "")) for m in models}
        # 1) 优先精确匹配预定义聊天模型
        for pref in _PREFERRED_CHAT_MODELS:
            if pref in ids:
                logger.info("自动选择聊天模型: %s", pref)
                return pref
        # 2) 模糊匹配聊天模型关键词，跳过非聊天模型
        for mid in sorted(ids):
            low = mid.lower()
            if any(k in low for k in _NON_CHAT_KEYWORDS):
                continue
            if "qwen" in low or "llama" in low or "gemma" in low or "deepseek" in low:
                logger.info("自动选择聊天模型(模糊): %s", mid)
                return mid
        logger.warning("未找到聊天模型，回退默认 %s", DEFAULT_MODEL)
        return DEFAULT_MODEL