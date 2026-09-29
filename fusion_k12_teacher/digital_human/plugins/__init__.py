"""4 层标准化插件接口 — TLive-Omni pattern 3。

ASR/LLM/TTS/Avatar 抽象基类, 解耦调度与推理。各插件声明 name/init/close/cancel/clear。
"""

from __future__ import annotations

from .base import ASRPlugin, AvatarPlugin, LLMPlugin, PluginUnavailable, TTSPlugin

__all__ = ["ASRPlugin", "AvatarPlugin", "LLMPlugin", "PluginUnavailable", "TTSPlugin"]
