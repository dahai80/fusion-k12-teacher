"""LiveKitAdapter — LiveKit SFU 适配层。

token 签名 / room 连接 / 音视频轨道发布 / DataChannel 状态广播。
- 视频轨: VideoSource(256,256) ← BGR 帧 (MuseTalk 输出) 转 RGBA。
- 音频轨: AudioSource(24kHz,1) ← TTS PCM int16。
- 数据: publish_state 广播 FSM/emotion; on_data 收学生 raise_hand/mic 事件。
livekit 包缺失时降级为 WS-only (无媒体, 文本+TTS 音频走 WS)。
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:
    from livekit import api as _lk_api
    from livekit import rtc as _lk_rtc
    _HAS_LIVEKIT = True
except Exception:
    _lk_api = None
    _lk_rtc = None
    _HAS_LIVEKIT = False

_RGBA_TYPE = 0  # VideoBufferType.RGBA


def _load_linguakids_env() -> tuple[str, str, str]:
    for p in (
        Path.home() / "business" / "linguakids-mvp" / "configs" / ".env",
        Path.home() / "fusion" / "fusion-k12-teacher" / ".env",
    ):
        if not p.exists():
            continue
        key = secret = url = ""
        for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line.startswith("LIVEKIT_API_KEY="):
                key = line.split("=", 1)[1].strip()
            elif line.startswith("LIVEKIT_API_SECRET="):
                secret = line.split("=", 1)[1].strip()
            elif line.startswith("LIVEKIT_URL="):
                url = line.split("=", 1)[1].strip()
        if key and secret:
            return key, secret, url
    return "", "", ""


class LiveKitAdapter:
    def __init__(self, session_id: str = "") -> None:
        self.session_id = session_id
        self.url = os.environ.get("FUSION_K12_LIVEKIT_URL", "ws://127.0.0.1:7880")
        self.api_key = os.environ.get("FUSION_K12_LIVEKIT_API_KEY", "")
        self.api_secret = os.environ.get("FUSION_K12_LIVEKIT_API_SECRET", "")
        if not (self.api_key and self.api_secret):
            lk_key, lk_secret, lk_url = _load_linguakids_env()
            if lk_key:
                self.api_key = self.api_key or lk_key
                self.api_secret = self.api_secret or lk_secret
                if lk_url and self.url == "ws://127.0.0.1:7880":
                    self.url = lk_url
                logger.info("livekit_adapter[%s]: 复用 linguakids LiveKit 配置 url=%s", session_id, self.url)
        self._room: Any = None
        self._video_source: Any = None
        self._audio_source: Any = None
        self._video_track: Any = None
        self._audio_track: Any = None

    @property
    def available(self) -> bool:
        return _HAS_LIVEKIT and bool(self.api_key and self.api_secret)

    def sign_token(self, identity: str, room: str, ttl_seconds: int = 3600) -> str:
        if not _HAS_LIVEKIT:
            raise RuntimeError("livekit 包未安装, 无法签 token")
        if not (self.api_key and self.api_secret):
            raise RuntimeError("LiveKit API key/secret 未配置")
        from datetime import timedelta
        token = _lk_api.AccessToken(self.api_key, self.api_secret)
        token = token.with_identity(identity).with_name(identity)
        token = token.with_grants(_lk_api.VideoGrants(room_join=True, room=room))
        token = token.with_ttl(timedelta(seconds=ttl_seconds))
        return token.to_jwt()

    async def connect(self, room: str, token: str) -> bool:
        if not self.available:
            logger.info("livekit[%s]: 不可用, WS 降级 (无媒体)", self.session_id)
            return False
        try:
            self._room = _lk_rtc.Room()
            await self._room.connect(self.url, token)
            await self._publish_tracks()
            logger.info("livekit[%s]: 已连接 room=%s 音视频轨已发布", self.session_id, room)
            return True
        except Exception as exc:
            logger.error("livekit[%s]: 连接失败 %s, WS 降级", self.session_id, exc)
            self._room = None
            return False

    async def _publish_tracks(self) -> None:
        # 视频轨: 256x256 RGBA (MuseTalk 输出 BGR→RGBA)
        self._video_source = _lk_rtc.VideoSource(256, 256)
        self._video_track = _lk_rtc.LocalVideoTrack.create_video_track(
            "avatar_video", self._video_source)
        # 音频轨: 24kHz 单声道 PCM (TTS/Kokoro 输出)
        self._audio_source = _lk_rtc.AudioSource(24000, 1)
        self._audio_track = _lk_rtc.LocalAudioTrack.create_audio_track(
            "avatar_audio", self._audio_source)
        opts = _lk_rtc.TrackPublishOptions()
        await self._room.local_participant.publish_track(self._video_track, opts)
        await self._room.local_participant.publish_track(self._audio_track, opts)
        logger.info("livekit[%s]: video+audio 轨发布完成", self.session_id)

    async def publish_video_frame(self, frame_bgr: Any) -> None:
        if self._video_source is None or frame_bgr is None:
            return
        try:
            import cv2
            rgba = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGBA)
            vf = _lk_rtc.VideoFrame(256, 256, _RGBA_TYPE, rgba.tobytes())
            self._video_source.capture_frame(vf)
        except Exception as exc:
            logger.warning("livekit[%s]: 视频帧发布失败 %s", self.session_id, exc)

    async def publish_audio_pcm(self, pcm: bytes) -> None:
        if self._audio_source is None or not pcm:
            return
        try:
            n_samples = len(pcm) // 2
            af = _lk_rtc.AudioFrame(pcm, 24000, 1, n_samples)
            self._audio_source.capture_frame(af)
        except Exception as exc:
            logger.warning("livekit[%s]: 音频帧发布失败 %s", self.session_id, exc)

    async def publish_state(self, state: str, emotion: str = "") -> None:
        if self._room is None:
            return
        try:
            import json
            await self._room.local_participant.publish_data(
                json.dumps({"state": state, "emotion": emotion}).encode(),
                topic="lk.state",
            )
        except Exception as exc:
            logger.warning("livekit[%s]: 状态广播失败 %s", self.session_id, exc)

    def on_data(self, callback: Callable[[bytes, str], None]) -> None:
        if self._room is None:
            return
        def _on_data(data: bytes, participant: Any, topic: str, *args: Any) -> None:
            try:
                callback(data, topic or "")
            except Exception as exc:
                logger.warning("livekit[%s]: on_data 回调异常 %s", self.session_id, exc)
        self._room.on("data_received", _on_data)
        logger.info("livekit[%s]: 已注册 data_received 订阅", self.session_id)

    def on_track_subscribed(self, callback: Callable[[Any], None]) -> None:
        if self._room is None:
            return
        def _on_sub(track: Any, publication: Any, participant: Any) -> None:
            try:
                callback(track)
            except Exception as exc:
                logger.warning("livekit[%s]: on_track_subscribed 回调异常 %s", self.session_id, exc)
        self._room.on("track_subscribed", _on_sub)

    async def aclose(self) -> None:
        if self._room is not None:
            try:
                await self._room.disconnect()
            except Exception as exc:
                logger.warning("livekit[%s]: 断开失败 %s", self.session_id, exc)
            self._room = None
        self._video_source = None
        self._audio_source = None
        self._video_track = None
        self._audio_track = None
