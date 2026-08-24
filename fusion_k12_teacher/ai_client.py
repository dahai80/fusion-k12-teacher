"""Fusion-K12-Teacher AI 客户端 — 所有 AI 推理的唯一接口。

All LLM calls go through fusion-mlx's OpenAI-compatible HTTP API.
优先使用 fusion-core 的 FusionMLXClient；fusion-core 缺失时回退 httpx 直连。
No direct mlx or mlx-lm imports — every call is routed via fusion-mlx.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MLX_BASE_URL = os.environ.get(
    "FUSION_MLX_URL", "http://localhost:11432/v1"
)
DEFAULT_MODEL = os.environ.get("FUSION_MLX_MODEL", "Qwen3.5-9B-4bit")
_CONNECT_TIMEOUT = float(os.environ.get("FUSION_MLX_CONNECT_TIMEOUT", "10"))
_READ_TIMEOUT = float(os.environ.get("FUSION_MLX_READ_TIMEOUT", "120"))
_MAX_RETRIES = int(os.environ.get("FUSION_MLX_MAX_RETRIES", "2"))
_MODELS_CACHE_TTL = float(os.environ.get("FUSION_MLX_MODELS_TTL", "30"))

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

_HAS_FUSION_CORE = False
_FusionMLXClient: Any = None
try:
    from fusion_core.mlx_client import FusionMLXClient as _FusionMLXClient

    _HAS_FUSION_CORE = True
    logger.info("fusion_core 可用，使用 FusionMLXClient")
except ImportError:
    logger.info("fusion_core 不可用，回退 httpx 直连 fusion-mlx")


class MLXClient:
    """fusion-mlx HTTP 客户端 — 所有 AI 推理的唯一接口。

    优先 fusion-core 的 FusionMLXClient；缺失时 httpx 直连 /v1/chat/completions。
    Default base_url: http://localhost:11432/v1 (FUSION_MLX_URL 覆盖)。
    """

    def __init__(self, model: str = "", base_url: str = ""):
        self.base_url = (base_url or DEFAULT_MLX_BASE_URL).rstrip("/")
        self.model = model
        self._inner: Any = None
        self._httpx_client: Any = None
        self._auto_select_lock = asyncio.Lock()
        self._models_cache: list[dict[str, Any]] | None = None
        self._models_cache_ts: float = 0.0
        if _HAS_FUSION_CORE and _FusionMLXClient is not None:
            self._inner = _FusionMLXClient(base_url=self.base_url)
        logger.info(
            "MLXClient init base_url=%s model=%s fusion_core=%s",
            self.base_url, self.model or "(auto)", _HAS_FUSION_CORE,
        )

    async def __aenter__(self) -> MLXClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    @property
    def httpx_client(self):
        if self._httpx_client is None:
            import httpx

            self._httpx_client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(_READ_TIMEOUT, connect=_CONNECT_TIMEOUT),
                headers={"Authorization": f"Bearer {os.environ.get('FUSION_MLX_API_KEY', 'local')}"},
            )
        return self._httpx_client

    async def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        """Call fusion-mlx /v1/chat/completions — all LLM inference goes through fusion-mlx."""
        if not self.model:
            self.model = await self._auto_select_model()
        used_model = self.model or DEFAULT_MODEL
        if _HAS_FUSION_CORE and self._inner is not None:
            try:
                return await self._inner.chat_text(
                    model=used_model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except Exception as e:
                logger.warning("fusion_core chat_text 失败，回退 httpx: %s", e)
        return await self._chat_httpx(messages, used_model, temperature, max_tokens)

    async def _chat_httpx(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        import httpx

        payload = {
            "model": model or DEFAULT_MODEL,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                resp = await self.httpx_client.post("/chat/completions", json=payload)
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as e:
                last_exc = e
                if attempt < _MAX_RETRIES:
                    logger.warning("chat 重试 %d/%d: %s", attempt + 1, _MAX_RETRIES, e)
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                raise
        raise last_exc if last_exc else RuntimeError("chat failed")

    async def list_models(self) -> list[dict[str, Any]]:
        """列出 fusion-mlx 可用模型 — 带 TTL 缓存。"""
        now = time.monotonic()
        if self._models_cache is not None and (now - self._models_cache_ts) < _MODELS_CACHE_TTL:
            return self._models_cache
        if _HAS_FUSION_CORE and self._inner is not None:
            try:
                models = await self._inner.list_models()
                self._models_cache = models
                self._models_cache_ts = now
                return models
            except Exception as e:
                logger.warning("fusion_core list_models 失败，回退 httpx: %s", e)
        resp = await self.httpx_client.get("/models")
        resp.raise_for_status()
        models = resp.json().get("data", [])
        self._models_cache = models
        self._models_cache_ts = now
        return models

    async def _auto_select_model(self) -> str:
        """自动选择可用聊天模型 — 优先匹配已知聊天模型，跳过非聊天模型。"""
        async with self._auto_select_lock:
            if self.model:
                return self.model
            try:
                models = await self.list_models()
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
                    self.model = pref
                    return pref
            # 2) 模糊匹配聊天模型关键词，跳过非聊天模型
            for mid in sorted(ids):
                low = mid.lower()
                if any(k in low for k in _NON_CHAT_KEYWORDS):
                    continue
                if "qwen" in low or "llama" in low or "gemma" in low or "deepseek" in low:
                    logger.info("自动选择聊天模型(模糊): %s", mid)
                    self.model = mid
                    return mid
            logger.warning("未找到聊天模型，回退默认 %s", DEFAULT_MODEL)
            return DEFAULT_MODEL

    async def close(self) -> None:
        if self._httpx_client is not None:
            await self._httpx_client.aclose()
            self._httpx_client = None
