# Fusion-K12-Teacher AI client — the single entry point for all AI inference.
#
# All LLM calls go through fusion-mlx's OpenAI-compatible HTTP API.
# Prefers fusion-core's FusionMLXClient; falls back to direct httpx when fusion-core is missing.
# No direct mlx or mlx-lm imports — every call is routed via fusion-mlx.

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import httpx

from ._keys import gateway_client_key
from .errors import NonDegradableError, classify_http_status

logger = logging.getLogger(__name__)

_FALLBACK_URL = "http://localhost:11432/v1"
_FALLBACK_MODEL = "Qwen3.5-9B-4bit"


def _env_url() -> str:
    return os.environ.get("FUSION_MLX_URL", _FALLBACK_URL)


def _env_model() -> str:
    return os.environ.get("FUSION_MLX_MODEL", _FALLBACK_MODEL)


# Cloud-mode switch (#28 migration review): when FUSION_MLX_CLOUD=1, all requests use strict OpenAI-compatible semantics.
#
#     Differences: 1) no chat_template_kwargs injected (strict cloud vendors 4xx-reject unknown fields)
#     2) no GBNF grammar (mlx-only constrained decoding, no cloud equivalent) 3) auto-select disabled
#     (cloud model names are unrelated to the local model library, FUSION_MLX_MODEL must be explicit).
def _cloud_mode() -> bool:
    return os.environ.get("FUSION_MLX_CLOUD", "").strip().lower() in ("1", "true", "yes")


_PREFERRED_CHAT_MODELS = (
    "Qwen3.5-9B-4bit", "Qwen3.5-9B", "Qwen3.5-4B", "Qwen3-4B",
    "Qwen3.5-4B-bf16", "Qwen3.5-4B-4bit", "Qwen3-0.6B",
    # Chat model verified to exist in the local mlx library (Llama-3.2-1B) — fallback when
    # no stronger model is available. Exact single-hyphen name: the double-hyphen variant
    # (--Llama) is not registered as an mlx entity and selecting it yields a 404 empty stream
    "mlx-community-Llama-3.2-1B-Instruct-4bit",
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


# P1-19: global LLM concurrency semaphore — caps simultaneously in-flight inference requests,
# preventing local single-device OOM / queue avalanche. scheduler._concurrency only covers
# agent tasks; ordinary engine concurrency is unbounded. Tunable via env.
_LLM_MAX_CONCURRENCY = int(os.environ.get("FUSION_MLX_MAX_CONCURRENCY", "4"))
_llm_semaphore: asyncio.Semaphore | None = None


def _llm_sem() -> asyncio.Semaphore:
    # Created lazily, bound to the current running loop (same rationale as _ensure_locks —
    # reusing a lock/semaphore across loops raises RuntimeError)
    global _llm_semaphore
    if _llm_semaphore is None:
        _llm_semaphore = asyncio.Semaphore(_LLM_MAX_CONCURRENCY)
    return _llm_semaphore


_HAS_FUSION_CORE = False
_FusionMLXClient: Any = None
try:
    from fusion_core.mlx_client import FusionMLXClient as _FusionMLXClient

    _HAS_FUSION_CORE = True
    logger.info("fusion_core available, using FusionMLXClient")
except ImportError:
    logger.info("fusion_core unavailable, falling back to direct httpx against fusion-mlx")


# fusion-mlx HTTP client — the single entry point for all AI inference.
#
#     Prefers fusion-core's FusionMLXClient; when absent, hits /v1/chat/completions directly via httpx.
#     base_url/model/timeouts are read from environment variables in __init__; changing env after
#     import and re-instantiating takes effect.
class MLXClient:

    def __init__(self, model: str = "", base_url: str = ""):
        self.base_url = (base_url or _env_url()).rstrip("/")
        # issue #18: read FUSION_MLX_MODEL env in __init__ — previously only model="" left it
        # empty, the env model was only assigned at first chat via _auto_select_model, so
        # self.model stayed empty before health probes and reported "auto", misleading ops.
        # Reading env at init lets health show the effective model.
        self.model = model or os.environ.get("FUSION_MLX_MODEL", "")
        self._inner: Any = None
        self._httpx_client: Any = None
        # LLM-5: locks are not created in __init__ — __init__ often runs without a live loop
        # (CLI group parsing); before 3.14 reusing a lock bound to a closed loop across
        # asyncio.run raises RuntimeError. Create lazily, bound to the current loop.
        self._auto_select_lock: asyncio.Lock | None = None
        self._cache_lock: asyncio.Lock | None = None
        self._models_cache: list[dict[str, Any]] | None = None
        self._models_cache_ts: float = 0.0
        self._connect_timeout = float(os.environ.get("FUSION_MLX_CONNECT_TIMEOUT", "10"))
        self._read_timeout = float(os.environ.get("FUSION_MLX_READ_TIMEOUT", "120"))
        self._max_retries = int(os.environ.get("FUSION_MLX_MAX_RETRIES", "2"))
        self._models_cache_ttl = float(os.environ.get("FUSION_MLX_MODELS_TTL", "30"))
        if _HAS_FUSION_CORE and _FusionMLXClient is not None:
            # fusion_core constructor hardcodes default timeout=120s and ignores env — long
            # inference with a 4B model (4096-token lecture script) would always time out,
            # so pass k12's FUSION_MLX_READ_TIMEOUT through
            self._inner = _FusionMLXClient(base_url=self.base_url, timeout=self._read_timeout)
        # R8: eager httpx client construction — the old lazy httpx_client property had no lock,
        # so concurrent first calls triggered a double-build and briefly leaked a pool instance.
        # Building in __init__ removes the race.
        self._httpx_client = self._build_httpx_client()
        logger.info(
            "MLXClient init base_url=%s model=%s fusion_core=%s max_concurrency=%d",
            self.base_url, self.model or "(auto)", _HAS_FUSION_CORE, _LLM_MAX_CONCURRENCY,
        )

    # LLM-5/R9: lazily create loop-bound locks — bind to the current running loop on first use.
    #
    #         R9: before 3.14, an asyncio.Lock created in __init__ (no loop yet) and reused across
    #         asyncio.run binds to the old (closed) loop and raises RuntimeError (cross-loop deadlock).
    #         Create lazily bound to the current loop; this instance must not be reused across loops —
    #         cli/serve each have their own loop, a shared client needs separate instances or one loop.
    #         This constraint is documented here, not enforced in code.
    def _ensure_locks(self) -> None:
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
        # R8: after eager construction this property just returns, no race.
        return self._httpx_client

    def _build_httpx_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(self._read_timeout, connect=self._connect_timeout),
        )

    def _auth_headers(self) -> dict[str, str]:
        # LLM-4: read env on every request so rotating the key at runtime takes effect
        # immediately, instead of being frozen at client construction.
        # P1-20: send no Bearer header when no key is set (the old default "Bearer local"
        # always got 401 from auth-required gateways).
        # #34: client key resolved via fusion_core.config as the single source
        # (see _keys.gateway_client_key).
        key = gateway_client_key()
        if key:
            return {"Authorization": f"Bearer {key}"}
        return {}

    # Call fusion-mlx /v1/chat/completions — all LLM inference goes through fusion-mlx.
    #
    #         A unified retry budget covers transient errors on both the fusion-core and httpx paths;
    #         a model 404 invalidates the cache and forces a re-select.
    #         model: override the default model (e.g. temporarily switch to a VLM for image Q&A: Qwen2.5-VL-7B).
    #         grammar: issue #20 GBNF grammar, passed through via gateway#184 to constrain output format.
    #         adapters: LoRA/DoRA adapter directory path, mounted in place by fusion-mlx (lora-inplace-swap).
    async def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        model: str = "",
        grammar: str | None = None,
        adapters: str | None = None,
    ) -> str:
        self._ensure_locks()
        if not self.model:
            self.model = await self._auto_select_model()
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            used_model = model or self.model or _env_model()
            try:
                sem = _llm_sem()
                await asyncio.wait_for(sem.acquire(), timeout=self._read_timeout + 30)
                try:
                    return await asyncio.wait_for(
                        self._dispatch_chat(messages, used_model, temperature, max_tokens, grammar, adapters),
                        timeout=self._read_timeout + 30,
                    )
                finally:
                    sem.release()
            except _RETRYABLE_ERRORS as e:
                last_exc = e
                if attempt < self._max_retries:
                    logger.warning("chat transient error/timeout, retry %d/%d: %s", attempt + 1, self._max_retries, e)
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                raise
            except _ModelNotFound as e:
                logger.warning("model not loaded (404), invalidating cache and re-selecting: %s", e)
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
        grammar: str | None = None,
        adapters: str | None = None,
    ) -> str:
        import time as _time
        _t0 = _time.monotonic()
        _ok = False
        think_kwargs = self._think_kwargs()
        try:
            # fusion_core chat_text does not support adapters — go straight to httpx when an
            # adapter is present (fusion-mlx mounts it in place)
            if adapters is None and _HAS_FUSION_CORE and self._inner is not None:
                try:
                    # cloud mode sends no GBNF grammar (mlx-only constrained decoding; cloud
                    # APIs have no such field and would reject it)
                    if grammar and not _cloud_mode():
                        extra_kwargs: dict[str, Any] = {"grammar": grammar}
                    else:
                        extra_kwargs: dict[str, Any] = {}
                    if think_kwargs:
                        extra_kwargs["chat_template_kwargs"] = think_kwargs
                    r = await self._inner.chat_text(
                        model=model,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        **extra_kwargs,
                    )
                    _ok = True
                    return r
                except NonDegradableError:
                    raise
                except Exception as e:
                    logger.warning("fusion_core chat_text failed, falling back to httpx: %s", e)
            r = await self._chat_httpx(messages, model, temperature, max_tokens, think_kwargs, grammar, adapters)
            _ok = True
            return r
        finally:
            # M3-T16: LLM call metrics — count + latency
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
        grammar: str | None = None,
        adapters: str | None = None,
    ) -> str:
        payload = {
            "model": model or _env_model(),
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if think_kwargs:
            payload["chat_template_kwargs"] = think_kwargs
        # cloud mode sends no GBNF grammar (mlx-only constrained decoding; no cloud field for it)
        if grammar and not _cloud_mode():
            payload["grammar"] = grammar
        # LoRA/DoRA in-place mount (fusion-mlx lora-inplace-swap), also mlx-specific
        if adapters and not _cloud_mode():
            payload["adapters"] = adapters
        resp = await self.httpx_client.post("/chat/completions", json=payload, headers=self._auth_headers())
        if resp.status_code == 404:
            raise _ModelNotFound(f"model not loaded: {model}")
        # A12: auth errors (401/403) and hard server errors (5xx) are non-degradable — must
        # propagate, never be swallowed into empty objects by engine blanket excepts.
        # classify runs before raise_for_status; on hit it raises NonDegradableError
        # (an EngineError subclass).
        if classify_http_status(resp.status_code):
            # P2: do not embed the response body (may contain student PII); report status code only
            raise NonDegradableError(f"LLM HTTP {resp.status_code}")
        resp.raise_for_status()
        # LLM-3: non-standard gateway payloads would crash on KeyError/IndexError without a
        # guard; degrade to empty string and log
        # P2: do not log the response body (PII risk), only the parse exception type
        try:
            body = resp.json()
            return body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as e:
            logger.error("unexpected LLM response structure, cannot parse content: %s", type(e).__name__)
            return ""

    # List available fusion-mlx models — with TTL cache and concurrency lock.
    async def list_models(self) -> list[dict[str, Any]]:
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
                logger.warning("fusion_core list_models failed, falling back to httpx: %s", e)
        resp = await self.httpx_client.get("/models", headers=self._auth_headers())
        resp.raise_for_status()
        return resp.json().get("data", [])

    # fusion-mlx /v1/audio/speech — Kokoro TTS. Returns audio bytes (wav/mp3/pcm).
    async def speech(
        self, text: str, *,
        voice: str = "",
        response_format: str = "wav",
        speed: float = 1.0,
    ) -> bytes:
        import time as _time
        _t0 = _time.monotonic()
        payload: dict[str, Any] = {
            "model": os.environ.get("FUSION_MLX_TTS_MODEL", "kokoro-82m"),
            "input": text,
            "response_format": response_format,
            "speed": speed,
        }
        if voice:
            payload["voice"] = voice
        # Direct TTS: the gateway may route /audio/speech to an unavailable Cloud backend
        # (observed 503 "Cloud backend not available"); a dedicated env lets TTS bypass the
        # gateway and hit fusion-mlx directly. Falls back to the original gateway path when unset.
        tts_url = os.environ.get("FUSION_MLX_TTS_URL", "").strip()
        if tts_url:
            client = self.httpx_client
            url = tts_url.rstrip("/") + "/audio/speech"
        else:
            client = self.httpx_client
            url = "/audio/speech"
        try:
            # use the TTS-specific key for direct mlx calls (mlx api_key != gateway key; wrong one gets 401)
            headers = self._auth_headers()
            tts_key = os.environ.get("FUSION_MLX_TTS_KEY", "").strip()
            if tts_url and tts_key:
                headers = {"Authorization": f"Bearer {tts_key}"}
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code >= 400:
                logger.error("TTS HTTP %d: %s", resp.status_code, resp.text[:200])
                raise RuntimeError(f"TTS HTTP {resp.status_code}")
            logger.info("TTS ok text=%d bytes format=%s took=%.1fs", len(text), response_format, _time.monotonic() - _t0)
            return resp.content
        except httpx.HTTPError as e:
            logger.error("TTS request failed: %s", e)
            raise

    # ASR — uses the gateway/direct endpoint /v1/audio/transcriptions (Whisper protocol) by default.
    #
    #         Cloud mode: the three envs FUSION_MLX_ASR_URL/KEY/MODEL point ASR independently at a
    #         cloud vendor endpoint (mirroring the TTS FUSION_MLX_TTS_URL/KEY/MODEL pattern);
    #         behavior is unchanged when unset.
    async def transcribe(
        self, audio: bytes, *,
        model: str = "",
        language: str = "zh",
    ) -> str:
        import time as _time
        _t0 = _time.monotonic()
        if not model:
            model = os.environ.get("FUSION_MLX_ASR_MODEL", "whisper-large-v3-turbo")
        files = {"file": ("audio.wav", audio, "audio/wav")}
        data: dict[str, Any] = {"model": model, "language": language, "word_timestamps": "false"}
        try:
            # dedicated ASR endpoint: enabled when the vendor's /audio/transcriptions
            # lives on a different origin than the main base_url
            asr_url = os.environ.get("FUSION_MLX_ASR_URL", "").strip()
            asr_key = os.environ.get("FUSION_MLX_ASR_KEY", "").strip()
            if asr_url:
                client = self._httpx_client
                url = asr_url.rstrip("/") + "/audio/transcriptions"
                headers = {"Authorization": f"Bearer {asr_key}"} if asr_key else {}
            else:
                client = self.httpx_client
                url = "/audio/transcriptions"
                headers = self._auth_headers()
            resp = await client.post(url, files=files, data=data, headers=headers)
            if resp.status_code >= 400:
                logger.error("ASR HTTP %d: %s", resp.status_code, resp.text[:200])
                raise RuntimeError(f"ASR HTTP {resp.status_code}")
            body = resp.json()
            text = body.get("text", "")
            logger.info("ASR ok text=%d chars took=%.1fs", len(text), _time.monotonic() - _t0)
            return text
        except httpx.HTTPError as e:
            logger.error("ASR request failed: %s", e)
            raise

    def _think_kwargs(self) -> dict[str, Any]:
        # Qwen3 models default to thinking (reasoning) mode; complex prompts can generate minutes
        # of reasoning_content. Teaching scenes need fast responses; set env
        # FUSION_MLX_ENABLE_THINKING=true to enable (default off).
        # Cloud mode (FUSION_MLX_CLOUD=1): not injected — strict cloud vendors 4xx-reject unknown fields.
        if _cloud_mode():
            return {}
        if os.environ.get("FUSION_MLX_ENABLE_THINKING", "").lower() in ("1", "true", "yes"):
            return {}
        return {"enable_thinking": False}

    # fusion-mlx /v1/chat/completions stream — SSE token stream. Returns an httpx.Response (streaming).
    #
    #         P1-19: streaming is not subject to the chat semaphore — in _answer streaming Q&A, TTS must
    #         run concurrently with the LLM stream (same semaphore would deadlock). Streaming inference is
    #         serialized within a single DH session (guaranteed by the fsm); cross-session concurrency is
    #         indirectly limited by the chat() semaphore.
    #         issue #20: enable_thinking parameter — None uses _think_kwargs() (env-controlled),
    #         True/False override explicitly (used by the two-stage CoT pipeline).
    #         issue #20 gap 2: grammar parameter — GBNF grammar passthrough (supported by gateway#184),
    #         constraining stage-2 DSL output to valid JSON, eliminating parse failures.
    async def chat_stream(
        self, messages: list[dict[str, str]], *, temperature: float = 0.7, max_tokens: int = 4096,
        enable_thinking: bool | None = None,
        grammar: str | None = None,
    ) -> Any:
        self._ensure_locks()
        if not self.model:
            self.model = await self._auto_select_model()
        # Model name prefers env: auto-select may pick a double-hyphen variant from the list
        # (mlx-community--X) while mlx entities only register the single-hyphen name, causing a
        # stream 404 and an empty stream (zero-word answers). The env name is verified to work.
        if enable_thinking is None:
            think_kwargs = self._think_kwargs()
        elif enable_thinking:
            think_kwargs = {}
        else:
            think_kwargs = {"enable_thinking": False}
        payload = {
            "model": _env_model() or self.model or _env_model(),
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
            "chat_template_kwargs": think_kwargs,
        }
        if grammar:
            payload["grammar"] = grammar
        logger.info("chat_stream: model=%s thinking=%s grammar=%s", payload["model"], think_kwargs, bool(grammar))
        return self.httpx_client.stream(
            "POST", "/chat/completions", json=payload, headers=self._auth_headers(),
        )

    # Auto-select an available chat model — prefer known chat models, skip non-chat models.
    #
    #         Disabled in cloud mode (FUSION_MLX_CLOUD=1): cloud model names are unrelated to the local
    #         mlx library, so scanning /v1/models against _PREFERRED_CHAT_MODELS would mis-select —
    #         FUSION_MLX_MODEL must be explicit.
    async def _auto_select_model(self, force: bool = False) -> str:
        async with self._auto_select_lock:
            if self.model and not force:
                return self.model
            if _cloud_mode():
                # cloud: do not scan the model list, use the explicit env model name
                # (surface an error when missing, never silently fall back)
                env_model = _env_model()
                logger.info("cloud mode: skipping auto-select, using explicit model %s", env_model or "(not set!)")
                self.model = env_model
                return self.model
            try:
                models = await self.list_models()
            except Exception:
                logger.warning("list_models failed, falling back to default model %s", _env_model())
                return _env_model()
            if not models:
                return _env_model()
            ids = {m.get("id", m.get("model", "")) for m in models}
            env_model = _env_model()
            if env_model and env_model in ids:
                logger.info("auto-selected chat model (env-specified): %s", env_model)
                self.model = env_model
                return env_model
            for pref in _PREFERRED_CHAT_MODELS:
                if pref in ids:
                    logger.info("auto-selected chat model: %s", pref)
                    self.model = pref
                    return pref
            for mid in sorted(ids):
                low = mid.lower()
                if any(k in low for k in _NON_CHAT_KEYWORDS):
                    continue
                if "qwen" in low or "llama" in low or "gemma" in low or "deepseek" in low:
                    logger.info("auto-selected chat model (fuzzy): %s", mid)
                    self.model = mid
                    return mid
            logger.warning("no chat model found, falling back to default %s", _env_model())
            return _env_model()

    async def close(self) -> None:
        # LLM-1: on the fusion-core path _inner holds an internal httpx client, release it too
        if self._inner is not None and hasattr(self._inner, "close"):
            try:
                await self._inner.close()
            except Exception as exc:
                logger.warning("FusionMLXClient.close failed: %s", exc)
        if self._httpx_client is not None:
            await self._httpx_client.aclose()
            self._httpx_client = None
