"""Digital-human platform layer — digital-human teacher (K2 real-time voice +
K3 digital human).

Subject-agnostic platform capabilities: 6 core designs (FSM/BargeIn/4-layer
plugins/emotion_tag/rolling memory/lifecycle), injects course content
(SubjectModule/LessonScripter), LiveKit SFU transport, no third-party repos
introduced.
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
