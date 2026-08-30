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

import httpx

from .errors import NonDegradableError, classify_http_status

logger = logging.getLogger(__name__)

_FALLBACK_URL = "http://localhost:11432/v1"
_FALLBACK_MODEL = "Qwen3.5-9B-4bit"


def _env_url() -> str:
    return os.environ.get("FUSION_MLX_URL", _FALLBACK_URL)


def _env_model() -> str:
    return os.environ.get("FUSION_MLX_MODEL", _FALLBACK_MODEL)


_PREFERRED_CHAT_MODELS = (
    "Qwen3.5-9B-4bit", "Qwen3.5-9B", "Qwen3.5-4B", "Qwen3-4B",
    "Qwen3.5-4B-bf16", "Qwen3.5-4B-4bit", "Qwen3-0.6B",
)
_NON_CHAT_KEYWORDS = (
    "dit", "vae", "text_encoder", "transformer", "embed", "bge",
    "siglip", "tts", "sdxl", "flux", "wan", "ltx", "skyreels",
    "pangu-embedded", "eagle3", "oldt5", "diffusion", "clip",
)

_TRANSIENT_ERRORS = (
    httpx.ConnectError, httpx.ConnectTimeout,
    httpx.ReadTimeout, httpx.RemoteProtocolError,
)


class _ModelNotFound(Exception):
    pass


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
    base_url/model/超时在 __init__ 读环境变量，支持 import 后改 env 再重建生效。
    """

    def __init__(self, model: str = "", base_url: str = ""):
        self.base_url = (base_url or _env_url()).rstrip("/")
        self.model = model or ""
        self._inner: Any = None
        self._httpx_client: Any = None
        # LLM-5: 锁不在 __init__ 创建 — __init__ 常在无运行循环时被调(CLI 组解析期),
        # 3.14 前跨 asyncio.run 复用已绑死循环的锁会 RuntimeError。改惰性建, 绑当前 loop。
        self._auto_select_lock: asyncio.Lock | None = None
        self._cache_lock: asyncio.Lock | None = None
        self._models_cache: list[dict[str, Any]] | None = None
        self._models_cache_ts: float = 0.0
        self._connect_timeout = float(os.environ.get("FUSION_MLX_CONNECT_TIMEOUT", "10"))
        self._read_timeout = float(os.environ.get("FUSION_MLX_READ_TIMEOUT", "120"))
        self._max_retries = int(os.environ.get("FUSION_MLX_MAX_RETRIES", "2"))
        self._models_cache_ttl = float(os.environ.get("FUSION_MLX_MODELS_TTL", "30"))
        if _HAS_FUSION_CORE and _FusionMLXClient is not None:
            self._inner = _FusionMLXClient(base_url=self.base_url)
        # R8: httpx client eager 构造 — 原 httpx_client property 惰性 init 无锁,
        # 多协程首调同时触发 double-build, 短暂泄漏一个连接池实例。__init__ 构造免竞态。
        self._httpx_client = self._build_httpx_client()
        logger.info(
            "MLXClient init base_url=%s model=%s fusion_core=%s",
            self.base_url, self.model or "(auto)", _HAS_FUSION_CORE,
        )

    def _ensure_locks(self) -> None:
        """LLM-5/R9: 惰性创建 loop-bound 锁 — 首次使用时绑定当前 running loop。

        R9: 3.14 前 asyncio.Lock 在 __init__(无循环) 创建后, 跨 asyncio.run 复用绑死旧
        (已关)循环的锁会 RuntimeError (跨 loop 死锁)。惰性建绑当前 loop, 但本实例
        禁止跨 loop 复用 — cli/serve 各自 loop, 共享 client 须各自独立实例或同 loop。
        此约束已文档化于 docstring, 不在代码层强制跨 loop 复用。
        """
        if self._cache_lock is None:
            self._cache_lock = asyncio.Lock()
        if self._auto_select_lock is None:
            self._auto_select_lock = asyncio.Lock()

    async def __aenter__(self) -> MLXClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    @property
    def httpx_client(self):
        # R8: eager 构造后此 property 仅直返, 无竞态。
        return self._httpx_client

    def _build_httpx_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(self._read_timeout, connect=self._connect_timeout),
        )

    def _auth_headers(self) -> dict[str, str]:
        # LLM-4: 每次请求读 env, 运行期换 key 即时生效, 不在客户端创建时固化
        return {"Authorization": f"Bearer {os.environ.get('FUSION_MLX_API_KEY', 'local')}"}

    async def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        """Call fusion-mlx /v1/chat/completions — all LLM inference goes through fusion-mlx。

        统一重试预算覆盖 fusion-core + httpx 双路径的瞬态错误；
        模型 404 时失效缓存并强制重新选择。
        """
        self._ensure_locks()
        if not self.model:
            self.model = await self._auto_select_model()
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            used_model = self.model or _env_model()
            try:
                return await self._dispatch_chat(messages, used_model, temperature, max_tokens)
            except _TRANSIENT_ERRORS as e:
                last_exc = e
                if attempt < self._max_retries:
                    logger.warning("chat 瞬态错误重试 %d/%d: %s", attempt + 1, self._max_retries, e)
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                raise
            except _ModelNotFound as e:
                logger.warning("模型未加载(404)，失效缓存并重新选择: %s", e)
                async with self._cache_lock:
                    self._models_cache = None
                    self._models_cache_ts = 0.0
                self.model = await self._auto_select_model(force=True)
                last_exc = e
                if attempt < self._max_retries:
                    continue
                raise
        raise last_exc if last_exc else RuntimeError("chat failed")

    async def _dispatch_chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        if _HAS_FUSION_CORE and self._inner is not None:
            try:
                return await self._inner.chat_text(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except Exception as e:
                logger.warning("fusion_core chat_text 失败，回退 httpx: %s", e)
        return await self._chat_httpx(messages, model, temperature, max_tokens)

    async def _chat_httpx(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        payload = {
            "model": model or _env_model(),
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        resp = await self.httpx_client.post("/chat/completions", json=payload, headers=self._auth_headers())
        if resp.status_code == 404:
            raise _ModelNotFound(f"模型未加载: {model}")
        # A12: 认证错(401/403)/服务端硬错(5xx)不可降级 — 须上抛暴露, 不被引擎 blanket except 吞成空对象。
        # classify 在 raise_for_status 前先判, 命中则抛 NonDegradableError (EngineError 子类)。
        if classify_http_status(resp.status_code):
            raise NonDegradableError(f"LLM HTTP {resp.status_code}: {str(resp.text)[:200]}")
        resp.raise_for_status()
        # LLM-3: 网关非标结构无 KeyError/IndexError 防御会直接崩, 降级空串并记日志
        try:
            body = resp.json()
            return body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as e:
            logger.error("LLM 响应结构异常, 无法解析 content: %s | body: %s", e, str(resp.text)[:300])
            return ""

    async def list_models(self) -> list[dict[str, Any]]:
        """列出 fusion-mlx 可用模型 — 带 TTL 缓存与并发锁。"""
        self._ensure_locks()
        now = time.monotonic()
        if self._models_cache is not None and (now - self._models_cache_ts) < self._models_cache_ttl:
            return self._models_cache
        async with self._cache_lock:
            now = time.monotonic()
            if self._models_cache is not None and (now - self._models_cache_ts) < self._models_cache_ttl:
                return self._models_cache
            models = await self._fetch_models()
            self._models_cache = models
            self._models_cache_ts = time.monotonic()
            return models

    async def _fetch_models(self) -> list[dict[str, Any]]:
        if _HAS_FUSION_CORE and self._inner is not None:
            try:
                return await self._inner.list_models()
            except Exception as e:
                logger.warning("fusion_core list_models 失败，回退 httpx: %s", e)
        resp = await self.httpx_client.get("/models", headers=self._auth_headers())
        resp.raise_for_status()
        return resp.json().get("data", [])

    async def _auto_select_model(self, force: bool = False) -> str:
        """自动选择可用聊天模型 — 优先匹配已知聊天模型，跳过非聊天模型。"""
        async with self._auto_select_lock:
            if self.model and not force:
                return self.model
            try:
                models = await self.list_models()
            except Exception:
                logger.warning("list_models 失败，回退默认模型 %s", _env_model())
                return _env_model()
            if not models:
                return _env_model()
            ids = {m.get("id", m.get("model", "")) for m in models}
            for pref in _PREFERRED_CHAT_MODELS:
                if pref in ids:
                    logger.info("自动选择聊天模型: %s", pref)
                    self.model = pref
                    return pref
            for mid in sorted(ids):
                low = mid.lower()
                if any(k in low for k in _NON_CHAT_KEYWORDS):
                    continue
                if "qwen" in low or "llama" in low or "gemma" in low or "deepseek" in low:
                    logger.info("自动选择聊天模型(模糊): %s", mid)
                    self.model = mid
                    return mid
            logger.warning("未找到聊天模型，回退默认 %s", _env_model())
            return _env_model()

    async def close(self) -> None:
        # LLM-1: 走 fusion-core 路径时 _inner 持有内部 httpx 客户端, 须一并释放
        if self._inner is not None and hasattr(self._inner, "close"):
            try:
                await self._inner.close()
            except Exception as exc:
                logger.warning("FusionMLXClient.close 失败: %s", exc)
        if self._httpx_client is not None:
            await self._httpx_client.aclose()
            self._httpx_client = None
