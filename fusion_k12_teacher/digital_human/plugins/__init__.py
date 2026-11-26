# 4-layer standardized plugin interface — TLive-Omni pattern 3.
#
# ASR/LLM/TTS/Avatar abstract base classes, decoupling scheduling from inference.
# Each plugin declares name/init/close/cancel/clear.

from __future__ import annotations

from .base import ASRPlugin, AvatarPlugin, LLMPlugin, PluginUnavailable, TTSPlugin

__all__ = ["ASRPlugin", "AvatarPlugin", "LLMPlugin", "PluginUnavailable", "TTSPlugin"]
