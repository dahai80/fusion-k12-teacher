"""插件基类 — ASR/LLM/TTS/Avatar 四层抽象。

各插件: name 属性, init()/close() 生命周期, available 属性, cancel()/clear() 供 BargeInBus 注册。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)


class PluginUnavailable(RuntimeError):
    pass


class _PluginBase(ABC):
    name: str = "base"

    @property
    def available(self) -> bool:
        return True

    async def init(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def cancel(self) -> None:
        pass

    def clear(self) -> None:
        pass


class ASRPlugin(_PluginBase):
    @abstractmethod
    async def transcribe(self, pcm: bytes) -> str:
        ...


class LLMPlugin(_PluginBase):
    @abstractmethod
    def stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        ...


class TTSPlugin(_PluginBase):
    @abstractmethod
    async def synthesize(self, text: str, emotion: str = "neutral") -> bytes:
        ...


class AvatarPlugin(_PluginBase):
    @abstractmethod
    async def render(self, text: str, pcm: bytes, emotion: str = "neutral") -> list[bytes]:
        ...

    @abstractmethod
    async def generate_idle_frames(self) -> list[bytes]:
        ...

    @abstractmethod
    def is_rendering(self, text: str) -> bool:
        ...

    @abstractmethod
    def cached_frames(self, text: str) -> list[bytes] | None:
        ...

    @abstractmethod
    async def stop_playback(self) -> None:
        ...

    @abstractmethod
    async def cancel_render(self) -> None:
        ...
