"""数字人平台层 — 数字人老师 (K2 实时语音 + K3 数字人)。

学科无关平台能力: 6 大核心设计 (FSM/BargeIn/4 层插件/emotion_tag/滚动记忆/生命周期),
注入课程内容 (SubjectModule/LessonScripter), LiveKit SFU 传输, 不引入第三方仓库。
"""

from __future__ import annotations

from .barge_in import BargeInBus
from .content import ContentInjector, NarrationSegment
from .emotion import EmotionTagParser
from .fsm import SessionFSM, SessionState
from .manager import DigitalHumanManager
from .memory import RollingWindowMemory
from .session import DigitalHumanSession

__all__ = [
    "BargeInBus", "ContentInjector", "DigitalHumanManager", "DigitalHumanSession",
    "EmotionTagParser", "NarrationSegment", "RollingWindowMemory",
    "SessionFSM", "SessionState",
]
