# Classroom module — K1 text version (classroom PRD E1-E6).
#
# Platform-content decoupling: classroom does not depend on specific subjects;
# scoring is delegated to AssessmentEngine/course verifier.
# LiveKit/digital-human/TTS upstream deferred (issue); K1 only teaches page by
# page in text + text answers.

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
