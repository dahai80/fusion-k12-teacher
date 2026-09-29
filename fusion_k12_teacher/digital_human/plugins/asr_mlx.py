"""MlxWhisperASR — fusion-mlx /v1/audio/transcriptions 插件。

word_timestamps=False 加速。asyncio.Lock 串行化 (单 GPU)。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .base import ASRPlugin

logger = logging.getLogger(__name__)


class MlxWhisperASR(ASRPlugin):
    name = "mlx_whisper_asr"

    def __init__(self, mlx_client: Any, *, model: str = "whisper-large-v3-turbo", language: str = "zh") -> None:
        self._mlx = mlx_client
        self._model = model
        self._language = language
        self._lock = asyncio.Lock()
        self._available = False

    @property
    def available(self) -> bool:
        return self._available

    async def init(self) -> None:
        if self._mlx is None:
            logger.warning("asr_mlx: mlx_client 为 None, 不可用")
            self._available = False
            return
        self._available = True
        logger.info("asr_mlx: init model=%s", self._model)

    async def transcribe(self, pcm: bytes) -> str:
        if not self._available or not pcm:
            return ""
        async with self._lock:
            try:
                return await self._mlx.transcribe(pcm, model=self._model, language=self._language)
            except Exception as exc:
                logger.error("asr_mlx: 转写失败 %s", exc)
                return ""

    async def cancel(self) -> None:
        pass

    def clear(self) -> None:
        pass

    async def close(self) -> None:
        pass
