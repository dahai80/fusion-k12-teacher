# DigitalHumanManager — digital human platform manager (serve.py lifecycle singleton).
#
# Prewarms shared plugin pipelines; create_session carries a concurrency gate
# (BoundedSemaphore MAX_SESSIONS); aclose drains all sessions on shutdown.
# Holds references to mlx_client/subject_registry/session_manager/lesson_scripter.

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from ..classroom.models import new_id
from .content import ContentInjector
from .plugins.base import ASRPlugin, AvatarPlugin, LLMPlugin, TTSPlugin
from .session import DigitalHumanSession

logger = logging.getLogger(__name__)

MAX_SESSIONS = 10
# Gate acquisition timeout — fails fast when callers forget to finish, never hangs forever
_GATE_TIMEOUT = float(os.environ.get("FUSION_K12_DH_GATE_TIMEOUT", "60"))


async def _fusion_mlx_service_up(base_url: str) -> bool:
    # Probes whether a local fusion-mlx HTTP service is running — when the same-machine GPU is
    # already occupied by the service process, in-process MuseTalk triggers an uncatchable
    # metal::malloc OOM (upstream issue #956) that hard-crashes the host process.
    # If detected, degrade to StaticAvatar.
    try:
        import httpx

        # #34: client key resolved via fusion_core.config as the single point
        from fusion_k12_teacher._keys import gateway_client_key
        key = gateway_client_key()
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        root = base_url[:-3] if base_url.endswith("/v1") else base_url
        async with httpx.AsyncClient(timeout=2.0) as c:
            r = await c.get(root + "/v1/models", headers=headers)
            return r.status_code == 200
    except Exception:
        return False


class DigitalHumanManager:
    def __init__(
        self,
        mlx_client: Any | None = None,
        subject_registry: Any | None = None,
        session_manager: Any | None = None,
        lesson_scripter: Any | None = None,
        *,
        max_sessions: int = MAX_SESSIONS,
    ) -> None:
        self.mlx_client = mlx_client
        self.subject_registry = subject_registry
        self.session_manager = session_manager
        self.lesson_scripter = lesson_scripter
        self._gate = asyncio.BoundedSemaphore(max_sessions)
        self._sessions: dict[str, DigitalHumanSession] = {}
        self._lock = asyncio.Lock()
        self._started = False
        self._tts: TTSPlugin | None = None
        self._asr: ASRPlugin | None = None
        self._llm: LLMPlugin | None = None
        self._avatar: AvatarPlugin | None = None

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        try:
            await self._prewarm()
        except Exception as exc:
            logger.error("manager: prewarm failed %s (degraded, plugins initialize on demand)", exc)
        logger.info("manager: startup complete max_sessions=%d", self._gate._bound_value if hasattr(self._gate, "_bound_value") else MAX_SESSIONS)

    async def _prewarm(self) -> None:
        from .plugins.avatar_static import StaticAvatar
        # When a same-machine fusion-mlx service is running, in-process MuseTalk triggers an
        # uncatchable OOM (issue #956) that hard-crashes the host process. Unless explicitly forced
        # with FUSION_K12_MUSETALK_INPROCESS=1, degrade to StaticAvatar when the service is
        # detected (TTS/LLM/ASR still go over HTTP, only lip sync degrades).
        force_inprocess = os.environ.get("FUSION_K12_MUSETALK_INPROCESS", "").strip() in ("1", "true", "yes")
        mlx_base = getattr(self.mlx_client, "base_url", "") or "http://localhost:11432/v1"
        cohost_up = await _fusion_mlx_service_up(mlx_base) if not force_inprocess else False
        if cohost_up:
            logger.warning("manager: fusion-mlx service running on same machine (%s), in-process MuseTalk would OOM crash, degrading to StaticAvatar (issue #956)", mlx_base)
        try:
            from .plugins.avatar_musetalk import MuseTalkAvatar
            musetalk = MuseTalkAvatar()
            await musetalk.init()
            if musetalk.available and not cohost_up:
                self._avatar = musetalk
                logger.info("manager: prewarm MuseTalkAvatar available=True")
            else:
                reason = "cohost-oom-guard" if cohost_up else ("unavailable" if not musetalk.available else "unknown")
                logger.info("manager: MuseTalkAvatar skipped (%s), falling back to StaticAvatar", reason)
                self._avatar = StaticAvatar()
                await self._avatar.init()
        except Exception as exc:
            logger.warning("manager: MuseTalkAvatar prewarm failed %s, falling back to StaticAvatar", exc)
            self._avatar = StaticAvatar()
            await self._avatar.init()
        logger.info("manager: prewarm avatar=%s done", self._avatar.name)
        if self.mlx_client is not None:
            try:
                from .plugins.tts_kokoro import KokoroTTS
                self._tts = KokoroTTS(self.mlx_client)
                await self._tts.init()
                logger.info("manager: prewarm KokoroTTS available=%s", self._tts.available)
            except Exception as exc:
                logger.warning("manager: KokoroTTS prewarm failed %s", exc)
            try:
                from .plugins.llm_mlx import MlxLLM
                self._llm = MlxLLM(self.mlx_client)
                await self._llm.init()
                logger.info("manager: prewarm MlxLLM available=%s", self._llm.available)
            except Exception as exc:
                logger.warning("manager: MlxLLM prewarm failed %s", exc)
            try:
                from .plugins.asr_mlx import MlxWhisperASR
                self._asr = MlxWhisperASR(self.mlx_client)
                await self._asr.init()
                logger.info("manager: prewarm MlxWhisperASR available=%s", self._asr.available)
            except Exception as exc:
                logger.warning("manager: MlxWhisperASR prewarm failed %s", exc)

    async def create_session(
        self, subject: str, topic: str, grade: str, *,
        code: str = "", student_id: str = "",
        layer: str = "B",
        lesson_plan: dict[str, Any] | None = None,
        mode: str = "topic",
        knowledge_node_id: str = "",
    ) -> DigitalHumanSession:
        # Gate with timeout — prevents create_session from blocking forever when callers forget
        # to finish (issue: gate exhaustion). On timeout fail fast; the caller gets a 503 instead of a hang.
        try:
            await asyncio.wait_for(self._gate.acquire(), timeout=_GATE_TIMEOUT)
        except TimeoutError:
            logger.warning("manager: DH concurrency gate timed out (active sessions >= %d), refusing new session", MAX_SESSIONS)
            raise RuntimeError(f"DH concurrency full (max={MAX_SESSIONS}), finish old sessions first")
        session_id = new_id("dh-")
        # Gate already acquired; if anything fails before the session is registered into _sessions
        # it must be released, otherwise the quota leaks permanently (after MAX_SESSIONS cumulative
        # failures the service rejects all new sessions until restart) — issue #13
        try:
            content = ContentInjector(self.subject_registry, self.lesson_scripter)
            avatar = self._avatar or await self._fallback_avatar()
            sess = DigitalHumanSession(
                session_id, subject, topic, grade,
                code=code, student_id=student_id,
                content=content, asr=self._asr, llm=self._llm, tts=self._tts,
                avatar=avatar, session_manager=self.session_manager, layer=layer,
                mode=mode, knowledge_node_id=knowledge_node_id,
            )
            async with self._lock:
                self._sessions[session_id] = sess
            # issue #16: idle-timeout watchdog auto-finish — goes through the unified finish path to release the gate
            sess._idle_finish_cb = self._make_idle_finish_cb(session_id)
            await sess.start(lesson_plan=lesson_plan)
        except Exception:
            self._gate.release()
            raise
        logger.info("manager: session created %s subject=%s topic=%s", session_id, subject, topic)
        return sess

    # issue #16: idle-timeout auto-finish callback — reuses the unified finish (pop + gate release).
    def _make_idle_finish_cb(self, session_id: str):
        async def _cb() -> None:
            logger.info("manager: session %s idle timeout, auto-finishing", session_id)
            await self.finish(session_id)
        return _cb

    async def _fallback_avatar(self) -> AvatarPlugin:
        from .plugins.avatar_static import StaticAvatar
        av = StaticAvatar()
        await av.init()
        return av

    def get(self, session_id: str) -> DigitalHumanSession | None:
        return self._sessions.get(session_id)

    async def finish(self, session_id: str) -> dict[str, Any] | None:
        sess = self._sessions.pop(session_id, None)
        if sess is None:
            return None
        try:
            res = await sess.finish()
        finally:
            self._gate.release()
        return res

    async def aclose(self) -> None:
        logger.info("manager: shutting down, draining %d sessions", len(self._sessions))
        for sid in list(self._sessions.keys()):
            try:
                await self.finish(sid)
            except Exception as exc:
                logger.warning("manager: session drain error %s %s", sid, exc)
        self._started = False
