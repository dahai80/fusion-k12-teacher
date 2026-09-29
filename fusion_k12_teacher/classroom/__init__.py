"""课堂模块 — K1 文字版 (classroom PRD E1-E6)。

平台-内容解耦: classroom 不依赖具体学科, 判分委托 AssessmentEngine/course verifier。
LiveKit/数字人/TTS 上游 deferred (issue), K1 仅文字逐页讲课 + 文字作答。
"""

from __future__ import annotations

from .models import (
    AnswerRecord,
    ClassReport,
    ClassSession,
    CoursePackage,
    LessonScript,
    ScriptPage,
)
from .packager import Packager
from .scripter import LessonScripter
from .session import SessionManager
from .store import ClassroomStore

__all__ = [
    "AnswerRecord",
    "ClassReport",
    "ClassSession",
    "ClassroomStore",
    "CoursePackage",
    "LessonScript",
    "LessonScripter",
    "Packager",
    "ScriptPage",
    "SessionManager",
]
