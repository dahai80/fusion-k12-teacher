"""DigitalHumanManager — 数字人平台管理器 (serve.py 生命周期单例)。

prewarm 共享插件管线; create_session 带并发闸门 (BoundedSemaphore MAX_SESSIONS);
aclose 关停时排空所有会话。持 mlx_client/subject_registry/session_manager/lesson_scripter 引用。
"""

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
# 闸门获取超时 — 调用方忘 finish 时快失败, 不永久挂死
_GATE_TIMEOUT = float(os.environ.get("FUSION_K12_DH_GATE_TIMEOUT", "60"))


async def _fusion_mlx_service_up(base_url: str) -> bool:
    # 探测本地 fusion-mlx HTTP 服务是否在跑 — 同机 GPU 已被服务进程占用时,
    # 进程内 MuseTalk 会触发不可捕获的 metal::malloc OOM (上游 issue #956),
    # 直接 hard-crash 宿主进程。探测到则降级 StaticAvatar。
    try:
        import httpx
        key = os.environ.get("FUSION_MLX_API_KEY", "")
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
            logger.error("manager: prewarm 失败 %s (降级, 插件按需初始化)", exc)
        logger.info("manager: 启动完成 max_sessions=%d", self._gate._bound_value if hasattr(self._gate, "_bound_value") else MAX_SESSIONS)

    async def _prewarm(self) -> None:
        from .plugins.avatar_static import StaticAvatar
        # 同机 fusion-mlx 服务在跑时, 进程内 MuseTalk 触发不可捕获 OOM (issue #956),
        # hard-crash 宿主进程。除非显式 FUSION_K12_MUSETALK_INPROCESS=1 强制开启,
        # 探测到服务则降级 StaticAvatar (TTS/LLM/ASR 仍走 HTTP, 仅唇形同步降级)。
        force_inprocess = os.environ.get("FUSION_K12_MUSETALK_INPROCESS", "").strip() in ("1", "true", "yes")
        mlx_base = getattr(self.mlx_client, "base_url", "") or "http://localhost:11432/v1"
        cohost_up = await _fusion_mlx_service_up(mlx_base) if not force_inprocess else False
        if cohost_up:
            logger.warning("manager: fusion-mlx 服务同机运行 (%s), 进程内 MuseTalk 将 OOM crash, 降级 StaticAvatar (issue #956)", mlx_base)
        try:
            from .plugins.avatar_musetalk import MuseTalkAvatar
            musetalk = MuseTalkAvatar()
            await musetalk.init()
            if musetalk.available and not cohost_up:
                self._avatar = musetalk
                logger.info("manager: prewarm MuseTalkAvatar available=True")
            else:
                reason = "cohost-oom-guard" if cohost_up else ("unavailable" if not musetalk.available else "unknown")
                logger.info("manager: MuseTalkAvatar 跳过 (%s), 回退 StaticAvatar", reason)
                self._avatar = StaticAvatar()
                await self._avatar.init()
        except Exception as exc:
            logger.warning("manager: MuseTalkAvatar prewarm 失败 %s, 回退 StaticAvatar", exc)
            self._avatar = StaticAvatar()
            await self._avatar.init()
        logger.info("manager: prewarm avatar=%s 完成", self._avatar.name)
        if self.mlx_client is not None:
            try:
                from .plugins.tts_kokoro import KokoroTTS
                self._tts = KokoroTTS(self.mlx_client)
                await self._tts.init()
                logger.info("manager: prewarm KokoroTTS available=%s", self._tts.available)
            except Exception as exc:
                logger.warning("manager: KokoroTTS prewarm 失败 %s", exc)
            try:
                from .plugins.llm_mlx import MlxLLM
                self._llm = MlxLLM(self.mlx_client)
                await self._llm.init()
                logger.info("manager: prewarm MlxLLM available=%s", self._llm.available)
            except Exception as exc:
                logger.warning("manager: MlxLLM prewarm 失败 %s", exc)
            try:
                from .plugins.asr_mlx import MlxWhisperASR
                self._asr = MlxWhisperASR(self.mlx_client)
                await self._asr.init()
                logger.info("manager: prewarm MlxWhisperASR available=%s", self._asr.available)
            except Exception as exc:
                logger.warning("manager: MlxWhisperASR prewarm 失败 %s", exc)

    async def create_session(
        self, subject: str, topic: str, grade: str, *,
        code: str = "", student_id: str = "",
        layer: str = "B",
        lesson_plan: dict[str, Any] | None = None,
    ) -> DigitalHumanSession:
        # 闸门带超时 — 避调用方忘 finish 时 create_session 永久阻塞 (issue: gate 耗尽)
        # 超时则快失败, 调用方收 503 而非挂死
        try:
            await asyncio.wait_for(self._gate.acquire(), timeout=_GATE_TIMEOUT)
        except TimeoutError:
            logger.warning("manager: DH 并发闸门超时 (活跃会话≥%d), 拒绝新建", MAX_SESSIONS)
            raise RuntimeError(f"DH 并发已满 (max={MAX_SESSIONS}), 请先 finish 旧会话")
        session_id = new_id("dh-")
        # 闸门已获取, 会话注册进 _sessions 前若失败须 release, 否则配额永久泄漏
        # (累计 MAX_SESSIONS 次失败后服务拒所有新建, 只能重启) — issue #13
        try:
            content = ContentInjector(self.subject_registry, self.lesson_scripter)
            avatar = self._avatar or await self._fallback_avatar()
            sess = DigitalHumanSession(
                session_id, subject, topic, grade,
                code=code, student_id=student_id,
                content=content, asr=self._asr, llm=self._llm, tts=self._tts,
                avatar=avatar, session_manager=self.session_manager, layer=layer,
            )
            async with self._lock:
                self._sessions[session_id] = sess
            # issue #16: 空闲超时 watchdog 自动 finish — 走统一 finish 路径释放闸门
            sess._idle_finish_cb = self._make_idle_finish_cb(session_id)
            await sess.start(lesson_plan=lesson_plan)
        except Exception:
            self._gate.release()
            raise
        logger.info("manager: 创建会话 %s subject=%s topic=%s", session_id, subject, topic)
        return sess

    def _make_idle_finish_cb(self, session_id: str):
        """issue #16: 空闲超时自动 finish 回调 — 复用统一 finish (pop+闸门释放)。"""
        async def _cb() -> None:
            logger.info("manager: 会话 %s 空闲超时, 自动结束", session_id)
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
        logger.info("manager: 关停 排空 %d 会话", len(self._sessions))
        for sid in list(self._sessions.keys()):
            try:
                await self.finish(sid)
            except Exception as exc:
                logger.warning("manager: 关停会话 %s 异常 %s", sid, exc)
        self._started = False
