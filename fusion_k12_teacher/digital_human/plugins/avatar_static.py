"""StaticAvatar — 始终可用的兜底数字人。

无 lip-sync, 仅 idle 帧 (breath/blink via Simulation)。
MuseTalk 不可用或降级时使用。
"""

from __future__ import annotations

import logging

from ..simulation import IdleMotion
from .base import AvatarPlugin

logger = logging.getLogger(__name__)

_IDLE_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00\x08\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff"
    b"\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff"
    b"\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff"
    b"\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff"
    b"\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
    b"\xff\xc4\x00\x14\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xfb\xff\xd9"
)


class StaticAvatar(AvatarPlugin):
    name = "static_avatar"

    def __init__(self, session_id: str = "") -> None:
        self.session_id = session_id
        self._sim = IdleMotion(session_id)
        self._speed = 1.0
        self._rendering_text: str | None = None
        self._cache: dict[str, list[bytes]] = {}

    @property
    def available(self) -> bool:
        return True

    async def init(self) -> None:
        logger.info("static_avatar[%s]: init", self.session_id)

    async def close(self) -> None:
        self._cache.clear()

    def set_speed(self, speed: float) -> None:
        self._speed = speed

    async def render(self, text: str, pcm: bytes, emotion: str = "neutral") -> list[bytes]:
        cached = self.cached_frames(text)
        if cached is not None:
            return cached
        self._rendering_text = text
        frames = [_IDLE_JPEG for _ in range(2)]
        self._cache[text] = frames
        self._rendering_text = None
        return frames

    async def generate_idle_frames(self) -> list[bytes]:
        return [_IDLE_JPEG]

    def is_rendering(self, text: str) -> bool:
        return self._rendering_text == text

    def cached_frames(self, text: str) -> list[bytes] | None:
        return self._cache.get(text)

    async def stop_playback(self) -> None:
        self._rendering_text = None

    async def cancel_render(self) -> None:
        self._rendering_text = None

    def clear(self) -> None:
        self._cache.clear()
