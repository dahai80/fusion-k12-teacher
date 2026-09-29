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
_RETRYABLE_ERRORS = (*_TRANSIENT_ERRORS, asyncio.TimeoutError)


class _ModelNotFound(Exception):
    pass


# P1-19: 全局 LLM 并发信号量 — 限制同时 in-flight 的推理请求数, 防本地单卡 OOM/排队雪崩。
# scheduler._concurrency 仅覆盖 agent 任务, 普通引擎并发无界。env 可调。
_LLM_MAX_CONCURRENCY = int(os.environ.get("FUSION_MLX_MAX_CONCURRENCY", "4"))
_llm_semaphore: asyncio.Semaphore | None = None


def _llm_sem() -> asyncio.Semaphore:
    # 惰性建, 绑当前 running loop (同 _ensure_locks 理由 — 跨 loop 复用锁/信号量会 RuntimeError)
    global _llm_semaphore
    if _llm_semaphore is None:
        _llm_semaphore = asyncio.Semaphore(_LLM_MAX_CONCURRENCY)
    return _llm_semaphore


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
            "MLXClient init base_url=%s model=%s fusion_core=%s max_concurrency=%d",
            self.base_url, self.model or "(auto)", _HAS_FUSION_CORE, _LLM_MAX_CONCURRENCY,
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
        # LLM-4: 每次请求读 env, 运行期换 key 即时生效, 不在客户端创建时固化。
        # P1-20: 无 key 时不发 Bearer 头 (原默认 Bearer local 对需认证网关必 401)。
        key = os.environ.get("FUSION_MLX_API_KEY", "")
        if key:
            return {"Authorization": f"Bearer {key}"}
        return {}

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
                # P1-19: 全局并发信号量限流 — 超并发请求排队等待, 不雪崩本地推理
                # 硬超时兜底 — fusion_core 连接卡死时 ReadTimeout 可能不触发, 防 sem 永久持有
                sem = _llm_sem()
                await asyncio.wait_for(sem.acquire(), timeout=self._read_timeout + 30)
                try:
                    return await asyncio.wait_for(
                        self._dispatch_chat(messages, used_model, temperature, max_tokens),
                        timeout=self._read_timeout + 30,
                    )
                finally:
                    sem.release()
            except _RETRYABLE_ERRORS as e:
                last_exc = e
                if attempt < self._max_retries:
                    logger.warning("chat 瞬态错误/超时重试 %d/%d: %s", attempt + 1, self._max_retries, e)
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
        import time as _time
        _t0 = _time.monotonic()
        _ok = False
        think_kwargs = self._think_kwargs()
        try:
            if _HAS_FUSION_CORE and self._inner is not None:
                try:
                    r = await self._inner.chat_text(
                        model=model,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        chat_template_kwargs=think_kwargs,
                    )
                    _ok = True
                    return r
                except NonDegradableError:
                    raise
                except Exception as e:
                    logger.warning("fusion_core chat_text 失败，回退 httpx: %s", e)
            r = await self._chat_httpx(messages, model, temperature, max_tokens, think_kwargs)
            _ok = True
            return r
        finally:
            # M3-T16: LLM 调用指标 — 计数 + 延迟
            try:
                from .metrics import get_metrics
                get_metrics().record_llm(model or "", _ok, _time.monotonic() - _t0)
            except Exception:
                pass

    async def _chat_httpx(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
        think_kwargs: dict | None = None,
    ) -> str:
        payload = {
            "model": model or _env_model(),
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if think_kwargs:
            payload["chat_template_kwargs"] = think_kwargs
        resp = await self.httpx_client.post("/chat/completions", json=payload, headers=self._auth_headers())
        if resp.status_code == 404:
            raise _ModelNotFound(f"模型未加载: {model}")
        # A12: 认证错(401/403)/服务端硬错(5xx)不可降级 — 须上抛暴露, 不被引擎 blanket except 吞成空对象。
        # classify 在 raise_for_status 前先判, 命中则抛 NonDegradableError (EngineError 子类)。
        if classify_http_status(resp.status_code):
            # P2: 不内嵌响应正文 (可能含学生 PII), 只报状态码 + 短由
            raise NonDegradableError(f"LLM HTTP {resp.status_code}")
        resp.raise_for_status()
        # LLM-3: 网关非标结构无 KeyError/IndexError 防御会直接崩, 降级空串并记日志
        # P2: 不记响应正文 (PII 风险), 只记解析异常类型
        try:
            body = resp.json()
            return body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as e:
            logger.error("LLM 响应结构异常, 无法解析 content: %s", type(e).__name__)
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

    async def speech(
        self, text: str, *,
        voice: str = "",
        response_format: str = "wav",
        speed: float = 1.0,
    ) -> bytes:
        """fusion-mlx /v1/audio/speech — Kokoro TTS。返回音频 bytes (wav/mp3/pcm)。"""
        import time as _time
        _t0 = _time.monotonic()
        payload: dict[str, Any] = {
            "model": "kokoro-82m",
            "input": text,
            "response_format": response_format,
            "speed": speed,
        }
        if voice:
            payload["voice"] = voice
        try:
            resp = await self.httpx_client.post("/audio/speech", json=payload, headers=self._auth_headers())
            if resp.status_code >= 400:
                logger.error("TTS HTTP %d: %s", resp.status_code, resp.text[:200])
                raise RuntimeError(f"TTS HTTP {resp.status_code}")
            logger.info("TTS ok text=%d字节 format=%s 耗时=%.1fs", len(text), response_format, _time.monotonic() - _t0)
            return resp.content
        except httpx.HTTPError as e:
            logger.error("TTS 请求失败: %s", e)
            raise

    async def transcribe(
        self, audio: bytes, *,
        model: str = "whisper-large-v3-turbo",
        language: str = "zh",
    ) -> str:
        """fusion-mlx /v1/audio/transcriptions — Whisper ASR。返回识别文本。"""
        import time as _time
        _t0 = _time.monotonic()
        files = {"file": ("audio.wav", audio, "audio/wav")}
        data: dict[str, Any] = {"model": model, "language": language, "word_timestamps": "false"}
        try:
            resp = await self.httpx_client.post(
                "/audio/transcriptions", files=files, data=data, headers=self._auth_headers(),
            )
            if resp.status_code >= 400:
                logger.error("ASR HTTP %d: %s", resp.status_code, resp.text[:200])
                raise RuntimeError(f"ASR HTTP {resp.status_code}")
            body = resp.json()
            text = body.get("text", "")
            logger.info("ASR ok 文本=%d字 耗时=%.1fs", len(text), _time.monotonic() - _t0)
            return text
        except httpx.HTTPError as e:
            logger.error("ASR 请求失败: %s", e)
            raise

    def _think_kwargs(self) -> dict[str, Any]:
        # Qwen3 系列默认开 thinking (reasoning) 模式, 复杂 prompt 生成数分钟 reasoning_content。
        # 教学场景需快速响应, env FUSION_MLX_ENABLE_THINKING=true 可开 (默认关)。
        if os.environ.get("FUSION_MLX_ENABLE_THINKING", "").lower() in ("1", "true", "yes"):
            return {}
        return {"enable_thinking": False}

    async def chat_stream(
        self, messages: list[dict[str, str]], *, temperature: float = 0.7, max_tokens: int = 4096,
    ) -> Any:
        """fusion-mlx /v1/chat/completions stream — SSE token 流。返回 httpx.Response (流式)。

        P1-19: 流式不纳入 chat 信号量 — _answer 流式答疑中 TTS 须与 LLM 流并发 (同 sem 死锁)。
        流式推理单 DH 会话内串行 (fsm 保证), 跨会话并发由 chat() 信号量间接限流。
        """
        self._ensure_locks()
        if not self.model:
            self.model = await self._auto_select_model()
        payload = {
            "model": self.model or _env_model(),
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
            "chat_template_kwargs": self._think_kwargs(),
        }
        return self.httpx_client.stream(
            "POST", "/chat/completions", json=payload, headers=self._auth_headers(),
        )

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
            env_model = _env_model()
            if env_model and env_model in ids:
                logger.info("自动选择聊天模型 (env 指定): %s", env_model)
                self.model = env_model
                return env_model
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
