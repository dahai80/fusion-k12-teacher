"""课堂模块数据模型 — K1 文字版 (LiveKit/数字人上游 deferred)。

对齐 fusion-k12-classroom-prd E1-E6: 课程包/讲稿/会话/作答/报告。
K1 文字版: 无 LiveKit 音视频, session 仅落库不签 token; 讲课以文字逐页呈现。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ScriptPage:
    page_index: int
    title: str = ""
    narration: str = ""
    slide_content: str = ""
    question_point: dict[str, Any] = field(default_factory=dict)
    emotion_tag: str = "neutral"

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_index": self.page_index, "title": self.title,
            "narration": self.narration, "slide_content": self.slide_content,
            "question_point": self.question_point, "emotion_tag": self.emotion_tag,
        }


@dataclass
class LessonScript:
    script_id: str
    subject: str
    grade: str
    topic: str
    pages: list[ScriptPage] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "script_id": self.script_id, "subject": self.subject,
            "grade": self.grade, "topic": self.topic,
            "pages": [p.to_dict() for p in self.pages], "error": self.error,
            "page_count": len(self.pages),
        }


@dataclass
class CoursePackage:
    class_id: str
    code: str
    subject: str
    grade: str
    topic: str
    lesson_plan: dict[str, Any] = field(default_factory=dict)
    slides: list[dict[str, Any]] = field(default_factory=list)
    quiz: dict[str, Any] = field(default_factory=dict)
    script: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    material_flags: dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "class_id": self.class_id, "code": self.code,
            "subject": self.subject, "grade": self.grade, "topic": self.topic,
            "lesson_plan": self.lesson_plan, "slides": self.slides,
            "quiz": self.quiz, "script": self.script,
            "created_at": self.created_at, "material_flags": self.material_flags,
            "page_count": len(self.script.get("pages", [])) if self.script else len(self.slides),
            "has_quiz": bool(self.quiz), "has_slides": bool(self.slides),
            "has_lesson_plan": bool(self.lesson_plan),
        }

    def to_manifest(self) -> dict[str, Any]:
        return {
            "class_id": self.class_id, "code": self.code,
            "subject": self.subject, "grade": self.grade, "topic": self.topic,
            "page_count": len(self.script.get("pages", [])) if self.script else len(self.slides),
            "has_quiz": bool(self.quiz), "has_slides": bool(self.slides),
            "has_lesson_plan": bool(self.lesson_plan),
            "material_flags": self.material_flags,
        }


@dataclass
class AnswerRecord:
    question_id: str
    student_answer: str
    correct: bool
    feedback: str = ""
    detail: str = ""
    timestamp: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id, "student_answer": self.student_answer,
            "correct": self.correct, "feedback": self.feedback,
            "detail": self.detail, "timestamp": self.timestamp,
        }


@dataclass
class ClassSession:
    session_id: str
    class_id: str
    code: str
    student_id: str
    status: str = "active"
    started_at: float = 0.0
    finished_at: float = 0.0
    pages_viewed: list[int] = field(default_factory=list)
    answers: list[AnswerRecord] = field(default_factory=list)
    questions_asked: int = 0
    abandoned: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id, "class_id": self.class_id,
            "code": self.code, "student_id": self.student_id,
            "status": self.status, "started_at": self.started_at,
            "finished_at": self.finished_at,
            "pages_viewed": self.pages_viewed,
            "answers": [a.to_dict() for a in self.answers],
            "questions_asked": self.questions_asked, "abandoned": self.abandoned,
        }


@dataclass
class ClassReport:
    session_id: str
    class_id: str
    student_id: str
    attendance: dict[str, Any] = field(default_factory=dict)
    pages_viewed: list[int] = field(default_factory=list)
    quiz_stat: dict[str, Any] = field(default_factory=dict)
    question_stat: dict[str, Any] = field(default_factory=dict)
    weak_points: list[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id, "class_id": self.class_id,
            "student_id": self.student_id, "attendance": self.attendance,
            "pages_viewed": self.pages_viewed, "quiz_stat": self.quiz_stat,
            "question_stat": self.question_stat, "weak_points": self.weak_points,
            "error": self.error,
        }


def new_id(prefix: str = "") -> str:
    return prefix + uuid.uuid4().hex[:12]


def now_ts() -> float:
    return time.time()
