"""DigitalHumanSession — digital human session.

Aggregates FSM + BargeInBus + Memory + ContentInjector + 4 plugins + Simulation + LiveKitAdapter.
Lifecycle: start() loads the script and publishes idle; narrate_page(idx) teaches via TTS+Avatar;
on_student_speech(pcm) handles barge-in into QA answering; idle_timeout releases MLX; finish() finalizes and persists.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from .barge_in import BargeInBus
from .content import ContentInjector, NarrationSegment
from .emotion import EmotionTagParser
from .fsm import SessionFSM, SessionState
from .livekit_adapter import LiveKitAdapter
from .memory import RollingWindowMemory
from .plugins.base import ASRPlugin, AvatarPlugin, LLMPlugin, TTSPlugin
from .simulation import IdleMotion

logger = logging.getLogger(__name__)

IDLE_TIMEOUT_SEC = 1800.0


class DigitalHumanSession:
    def __init__(
        self, session_id: str, subject: str, topic: str, grade: str,
        *,
        code: str = "", student_id: str = "",
        content: ContentInjector,
        asr: ASRPlugin | None = None,
        llm: LLMPlugin | None = None,
        tts: TTSPlugin | None = None,
        avatar: AvatarPlugin,
        livekit: LiveKitAdapter | None = None,
        session_manager: Any = None,
        layer: str = "B",
        idle_timeout: float = IDLE_TIMEOUT_SEC,
        mode: str = "topic",
        knowledge_node_id: str = "",
    ) -> None:
        self.session_id = session_id
        self.subject = subject
        self.topic = topic
        self.grade = grade
        self.code = code
        self.student_id = student_id
        self.layer = layer
        # Session mode: topic=free topic | course=follow lesson plan | expand=variant practice | qa=pure Q&A
        self.mode = mode
        self.knowledge_node_id = knowledge_node_id
        self.idle_timeout = idle_timeout

        self.fsm = SessionFSM(session_id)
        self.bus = BargeInBus(session_id)
        self.memory = RollingWindowMemory(session_id=session_id, level=layer)
        self.emotion = EmotionTagParser(session_id)
        self.sim = IdleMotion(session_id)
        self.content = content
        self.livekit = livekit or LiveKitAdapter(session_id)
        self.session_manager = session_manager

        self.asr = asr
        self.llm = llm
        self.tts = tts
        self.avatar = avatar

        self.segments: list[NarrationSegment] = []
        self._current_idx = 0
        self._last_active = time.monotonic()
        self._idle_task: asyncio.Task[None] | None = None
        self._narrate_task: asyncio.Task[None] | None = None
        self._speaking = False
        self._closed = False
        self._last_audio: bytes = b""
        self._class_session_id: str | None = None
        self._bg_tasks: set[asyncio.Task[None]] = set()
        self._finished = False
        # issue #16: idle-timeout auto-finish callback — injected by manager (must release the concurrency gate)
        self._idle_finish_cb: Callable[[], Awaitable[None]] | None = None

        self._wire_barge_in()
        self._wire_hooks()

    def _track_bg(self, task: asyncio.Task[None]) -> asyncio.Task[None]:
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)
        return task

    def _wire_barge_in(self) -> None:
        if self.tts is not None:
            self.bus.register("tts", self.tts.cancel, self.tts.clear)
        if self.avatar is not None:
            self.bus.register("avatar", self.avatar.cancel_render, self.avatar.clear)
        if self.asr is not None:
            self.bus.register("asr", self.asr.cancel, self.asr.clear)
        if self.llm is not None:
            self.bus.register("llm", self.llm.cancel, self.llm.clear)
        self.bus.register("narrate", self._cancel_narrate, None)
        self.fsm.bind_barge_in(self.bus)

    async def _cancel_narrate(self) -> None:
        if self._narrate_task is not None and not self._narrate_task.done():
            self._narrate_task.cancel()

    def _wire_hooks(self) -> None:
        async def _on_error(reason: str) -> None:
            logger.error("session[%s]: entering ERROR reason=%s", self.session_id, reason)
            await self.livekit.publish_state("error", reason)

        async def _on_enter_idle(reason: str) -> None:
            await self.livekit.publish_state("idle", "")

        async def _on_enter_speaking(reason: str) -> None:
            await self.livekit.publish_state("ai_speaking", "")

        self.fsm.register_hook("on_error", _on_error)
        self.fsm.register_hook("on_enter_" + SessionState.IDLE.value, _on_enter_idle)
        self.fsm.register_hook("on_enter_" + SessionState.AI_SPEAKING.value, _on_enter_speaking)

    async def start(self, *, lesson_plan: dict[str, Any] | None = None) -> int:
        self.memory.set_layers(course_context=self.content.build_course_context(
            self.subject, self.topic, self.grade))
        load_task = asyncio.create_task(self.content.load_lesson(
            self.subject, self.topic, self.grade, layer=self.layer,
            lesson_plan=lesson_plan,
            mode=self.mode, knowledge_node_id=self.knowledge_node_id,
        ))
        init_tasks = [p.init() for p in (self.asr, self.llm, self.tts, self.avatar) if p is not None]
        if init_tasks:
            await asyncio.gather(*init_tasks, return_exceptions=True)
        self.segments = await load_task
        idle = await self.avatar.generate_idle_frames()
        if self.livekit is not None and self.livekit._room is not None and idle:
            await self.livekit.publish_video_frame(self._decode_jpeg(idle[0]))
            self.livekit.on_data(self._on_livekit_data)
        if self.session_manager is not None and self.code:
            try:
                cs = self.session_manager.create_session(
                    class_id=self.code, code=self.code, student_id=self.student_id or "dh")
                self._class_session_id = cs.session_id
                logger.info("session[%s]: classroom session persisted %s", self.session_id, self._class_session_id)
            except Exception as exc:
                logger.warning("session[%s]: classroom session persist failed %s", self.session_id, exc)
        logger.info("session[%s]: started segments=%d idle_frames=%d", self.session_id, len(self.segments), len(idle))
        self._idle_task = asyncio.create_task(self._idle_watchdog())
        return len(self.segments)

    async def narrate_page(self, idx: int) -> dict[str, Any]:
        if idx < 0 or idx >= len(self.segments):
            return {"error": "idx out of range", "idx": idx}
        seg = self.segments[idx]
        self._current_idx = idx
        self._last_active = time.monotonic()
        self._narrate_task = asyncio.current_task()
        clean, tag = self.emotion.strip(seg.text)
        await self.fsm.transition(SessionState.AI_THINKING, reason=f"narrate:{idx}")
        try:
            pcm = b""
            if self.tts is not None and self.tts.available:
                await self.emotion.broadcast(tag, tts_cb=self._tts_set_speed)
                pcm = await self.tts.synthesize(clean, tag)
            self._last_audio = pcm
            frames: list[bytes] = []
            if self.avatar is not None:
                frames = await self.avatar.render(clean, pcm, tag)
            await self.fsm.transition(SessionState.AI_SPEAKING, reason=f"narrate:{idx}")
            self._speaking = True
            self.memory.add("assistant", clean, sticky=False)
            await self._publish_media(frames, pcm)
            self._speaking = False
            if self._class_session_id and self.session_manager is not None:
                try:
                    self.session_manager.record_page_view(self._class_session_id, idx)
                except Exception as exc:
                    logger.warning("session[%s]: record page view failed %s", self.session_id, exc)
            logger.info("session[%s]: narrate %d frames=%d pcm=%d", self.session_id, idx, len(frames), len(pcm))
            await self.fsm.transition(SessionState.IDLE, reason="narrate_done")
            self._narrate_task = None
            return {"idx": idx, "emotion": tag, "text": clean, "frames": len(frames),
                    "has_audio": bool(pcm), "audio_len": len(pcm),
                    "checkpoint": seg.checkpoint, "question": seg.question,
                    "title": seg.title, "phase": seg.phase}
        except asyncio.CancelledError:
            logger.info("session[%s]: narrate %d interrupted", self.session_id, idx)
            await self.fsm.transition(SessionState.IDLE, reason="narrate_cancelled")
            raise
        except Exception as exc:
            logger.error("session[%s]: narrate %d error %s", self.session_id, idx, exc)
            await self.fsm.transition(SessionState.ERROR, reason=str(exc))
            return {"error": str(exc), "idx": idx}

    async def _tts_set_speed(self, tag: str, speed: float) -> None:
        if self.tts is not None and hasattr(self.tts, "set_speed"):
            self.tts.set_speed(speed)

    @staticmethod
    def _decode_jpeg(jpg: bytes) -> Any:
        try:
            import cv2
            bgr = cv2.imdecode(bytearray(jpg), cv2.IMREAD_COLOR)
            return bgr
        except Exception:
            return None

    def _on_livekit_data(self, data: bytes, topic: str) -> None:
        # DataChannel student events: raise_hand (JSON) / mic pcm (binary, topic=lk.mic)
        if topic == "lk.mic":
            self._track_bg(asyncio.create_task(self.on_student_speech(data)))
        else:
            try:
                import json
                msg = json.loads(data.decode())
                if msg.get("action") == "raise_hand":
                    self._track_bg(asyncio.create_task(self.raise_hand(msg.get("text", ""))))
            except Exception as exc:
                logger.warning("session[%s]: livekit data parse failed %s", self.session_id, exc)

    async def _publish_media(self, frames: list[bytes], pcm: bytes) -> None:
        # LiveKit track publishing: audio in one shot (24kHz PCM), video decoded JPEG→BGR→RGBA at a 25fps pace.
        # Skipped on WS degradation (livekit._room None); audio still goes over WS binary (serve.py).
        # Aborts immediately when _speaking=False (barge-in triggered).
        if self.livekit is None or self.livekit._room is None:
            return
        if not self._speaking:
            logger.debug("session[%s]: _publish_media skipped (barge-in)", self.session_id)
            return
        if pcm:
            await self.livekit.publish_audio_pcm(pcm)
        if not frames:
            return
        try:
            import cv2
            frame_interval = 1.0 / 25.0
            for i, jpg in enumerate(frames):
                if self._closed or not self._speaking:
                    break
                bgr = cv2.imdecode(bytearray(jpg), cv2.IMREAD_COLOR)
                if bgr is None:
                    continue
                await self.livekit.publish_video_frame(bgr)
                if i < len(frames) - 1:
                    await asyncio.sleep(frame_interval)
        except Exception as exc:
            logger.warning("session[%s]: LiveKit media publish error %s", self.session_id, exc)

    async def on_student_speech(self, pcm: bytes) -> dict[str, Any]:
        self._last_active = time.monotonic()
        self._speaking = False
        if self._narrate_task is not None and not self._narrate_task.done():
            self._narrate_task.cancel()
            try:
                await self._narrate_task
            except (asyncio.CancelledError, Exception):
                pass
            self._narrate_task = None
        await self.bus.fire("student_speech")
        await self.fsm.transition(SessionState.USER_SPEAKING, reason="student_speech")
        text = ""
        if pcm and self.asr is not None and self.asr.available:
            text = await self.asr.transcribe(pcm)
        if not text:
            await self.fsm.transition(SessionState.IDLE, reason="empty_speech")
            return {"error": "empty_transcription"}
        return await self._answer(text)

    async def raise_hand(self, text: str, image_b64: str = "") -> dict[str, Any]:
        self._last_active = time.monotonic()
        self._speaking = False
        if self._narrate_task is not None and not self._narrate_task.done():
            self._narrate_task.cancel()
            try:
                await self._narrate_task
            except (asyncio.CancelledError, Exception):
                pass
            self._narrate_task = None
        await self.bus.fire("raise_hand")
        if not text and not image_b64:
            await self.fsm.transition(SessionState.IDLE, reason="empty_hand")
            return {"error": "empty_text"}
        # Image question (mode 3): with an image, run VLM first → merge the description into the question text (degrade to text-only on failure)
        if image_b64 and self.llm is not None and hasattr(self.llm, "describe_image"):
            # i18n: user-facing (LLM prompt text, Chinese teaching content)
            desc = await self.llm.describe_image(image_b64, text)
            if desc:
                text = f"{text}（学生上传了图片，图片内容: {desc}）" if text else f"请讲解图片中的题目: {desc}"
        if not text:
            await self.fsm.transition(SessionState.IDLE, reason="empty_hand")
            return {"error": "empty_text"}
        return await self._answer(text)

    async def _answer(self, text: str) -> dict[str, Any]:
        self.memory.add("user", text)
        await self.fsm.transition(SessionState.AI_THINKING, reason="qa")
        answer_parts: list[str] = []
        total_pcm = b""
        tag = "encouraging"
        if self.llm is not None and self.llm.available:
            await self.fsm.transition(SessionState.AI_SPEAKING, reason="qa_stream")
            self._speaking = True
            buf = ""
            # i18n: user-facing (Chinese sentence-end punctuation for streaming TTS split)
            sentence_ends = set("。！？!?；")
            async for tok in self.llm.stream(self.memory.build_messages()):
                if self._closed or not self._speaking:
                    break
                buf += tok
                answer_parts.append(tok)
                while buf:
                    cut = -1
                    for i, ch in enumerate(buf):
                        if ch in sentence_ends:
                            cut = i + 1
                            break
                    if cut < 0:
                        break
                    sentence = buf[:cut].strip()
                    buf = buf[cut:]
                    if not sentence:
                        continue
                    s_clean, s_tag = self.emotion.strip(sentence)
                    tag = s_tag or tag
                    if self.tts is not None and self.tts.available:
                        s_pcm = await self.tts.synthesize(s_clean, tag)
                    else:
                        s_pcm = b""
                    total_pcm += s_pcm
                    self._last_audio = s_pcm
                    if self.avatar is not None:
                        await self.avatar.render(s_clean, s_pcm, tag)
                    s_frames = self.avatar.cached_frames(s_clean) if self.avatar else []
                    await self._publish_media(s_frames, s_pcm)
            self._speaking = False
            if buf.strip():
                s_clean, s_tag = self.emotion.strip(buf)
                tag = s_tag or tag
                if self.tts is not None and self.tts.available:
                    s_pcm = await self.tts.synthesize(s_clean, tag)
                else:
                    s_pcm = b""
                total_pcm += s_pcm
                self._last_audio = s_pcm
                if self.avatar is not None:
                    await self.avatar.render(s_clean, s_pcm, tag)
                s_frames = self.avatar.cached_frames(s_clean) if self.avatar else []
                await self._publish_media(s_frames, s_pcm)
        else:
            # i18n: user-facing (spoken fallback answer to the student)
            answer_parts.append("我还需要想想这个问题。")
            clean, tag = self.emotion.strip("".join(answer_parts))
            if self.tts is not None and self.tts.available:
                total_pcm = await self.tts.synthesize(clean, tag)
            self._last_audio = total_pcm
            if self.avatar is not None:
                await self.avatar.render(clean, total_pcm, tag)
            await self.fsm.transition(SessionState.AI_SPEAKING, reason="qa")
            self._speaking = True
            qa_frames = self.avatar.cached_frames(clean) if self.avatar else []
            await self._publish_media(qa_frames, total_pcm)
            self._speaking = False
        clean = self.emotion.strip("".join(answer_parts))[0]
        self.memory.add("assistant", clean)
        if self._class_session_id and self.session_manager is not None:
            try:
                self.session_manager.record_question(self._class_session_id)
            except Exception as exc:
                logger.warning("session[%s]: record question failed %s", self.session_id, exc)
        await self.fsm.transition(SessionState.IDLE, reason="qa_done")
        logger.info("session[%s]: qa q=%s answer=%d chars pcm=%d", self.session_id, text[:20], len(clean), len(total_pcm))
        # Scene animation is not generated synchronously in the QA path (LLM extraction takes minutes, would lag the voice answer) —
        # the frontend calls /api/course/{subject}/scene-compile asynchronously after receiving the answer to load the animation
        return {"question": text, "answer": clean, "emotion": tag,
                "has_audio": bool(total_pcm), "audio_len": len(total_pcm)}

    async def _idle_watchdog(self) -> None:
        while not self._closed:
            await asyncio.sleep(10.0)
            if self._closed:
                break
            if time.monotonic() - self._last_active > self.idle_timeout:
                logger.info("session[%s]: idle timeout, releasing MLX resources", self.session_id)
                await self._release_mlx()
                self._last_active = time.monotonic()
                # issue #16: auto-finish the session and release the concurrency gate, preventing zombie sessions from holding quota forever
                cb = self._idle_finish_cb
                if cb is not None:
                    try:
                        await cb()
                    except Exception as exc:
                        logger.warning("session[%s]: idle auto-finish failed %s", self.session_id, exc)
                    return

    async def _release_mlx(self) -> None:
        try:
            import mlx.core as mx
            mx.clear_cache()
            logger.debug("session[%s]: mx.clear_cache done", self.session_id)
        except Exception:
            pass

    async def finish(self) -> dict[str, Any]:
        # issue #16: idempotent — watchdog auto-finish and explicit finish may trigger concurrently/in sequence
        if self._finished:
            return {"session_id": self.session_id, "finished": True,
                    "class_session_id": self._class_session_id}
        self._finished = True
        self._closed = True
        await self.bus.fire("finish")
        if self._idle_task and not self._idle_task.done():
            self._idle_task.cancel()
        for p in (self.asr, self.llm, self.tts, self.avatar):
            if p is not None:
                try:
                    await p.close()
                except Exception as exc:
                    logger.warning("session[%s]: plugin close error %s", self.session_id, exc)
        if self._class_session_id and self.session_manager is not None:
            try:
                self.session_manager.finish_session(self._class_session_id, abandoned=False)
            except Exception as exc:
                logger.warning("session[%s]: classroom session finish persist failed %s", self.session_id, exc)
        await self.livekit.aclose()
        logger.info("session[%s]: finished", self.session_id)
        return {"session_id": self.session_id, "finished": True,
                "class_session_id": self._class_session_id}

    @property
    def current_idx(self) -> int:
        return self._current_idx

    @property
    def page_count(self) -> int:
        return len(self.segments)

    def page_manifest(self) -> list[dict[str, Any]]:
        return [s.to_dict() for s in self.segments]
