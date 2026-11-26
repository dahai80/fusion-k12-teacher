"""KokoroTTS — fusion-mlx /v1/audio/speech plugin.

emotion -> speed mapping. Returns wav bytes. Same PCM feeds AvatarPlugin.render.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from ..emotion import EMOTION_SPEED
from ..zh_normalize import normalize_zh_speech
from .base import TTSPlugin

logger = logging.getLogger(__name__)

# Default Chinese female voice — Kokoro English voices are ineffective on pure
# Chinese input (silence/garbled sound); the digital-human teacher speaks
# Chinese by default, so a Chinese voice is the default; override via
# FUSION_K12_TTS_VOICE.
_DEFAULT_VOICE = os.environ.get("FUSION_K12_TTS_VOICE", "zf_xiaoxiao")


class KokoroTTS(TTSPlugin):
    name = "kokoro_tts"

    def __init__(self, mlx_client: Any, voice: str = "") -> None:
        self._mlx = mlx_client
        self._voice = voice or _DEFAULT_VOICE
        self._speed = 1.0
        self._available = False

    @property
    def available(self) -> bool:
        return self._available

    async def init(self) -> None:
        if self._mlx is None:
            logger.warning("tts_kokoro: mlx_client is None, unavailable")
            self._available = False
            return
        self._available = True
        logger.info("tts_kokoro: init voice=%s", self._voice or "(default)")

    def set_speed(self, speed: float) -> None:
        self._speed = speed

    async def synthesize(self, text: str, emotion: str = "neutral") -> bytes:
        if not self._available:
            return b""
        speed = EMOTION_SPEED.get(emotion, 1.0) * self._speed / max(self._speed, 0.01)
        speed = round(min(max(speed, 0.5), 2.0), 2)
        # Chinese speech normalization: fractions/percent/decimals/math symbols
        # -> Chinese readings (Kokoro G2P is weak on digits)
        text = normalize_zh_speech(text)
        try:
            return await self._mlx.speech(text, voice=self._voice, response_format="wav", speed=speed)
        except Exception as exc:
            logger.error("tts_kokoro: synthesis failed %s", exc)
            return b""

    async def cancel(self) -> None:
        pass

    def clear(self) -> None:
        pass

    async def close(self) -> None:
        pass
