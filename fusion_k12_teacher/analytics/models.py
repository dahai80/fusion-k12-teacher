"""学情分析数据模型。"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class StudentAssessment:
    """学生测评记录 — 学情数据输入单元。"""
    student_id: str = ""
    student_name: str = ""
    assessment_id: str = ""
    date: str = ""
    subject: str = ""
    grade: str = ""
    scores: dict[str, float] = field(default_factory=dict)
    responses: list[dict[str, Any]] = field(default_factory=list)
    total_score: float = 0.0
    max_score: float = 100.0

    @property
    def percentage(self) -> float:
        if self.max_score <= 0:
            return 0.0
        return round(self.total_score / self.max_score * 100, 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "student_id": self.student_id,
            "student_name": self.student_name,
            "assessment_id": self.assessment_id,
            "date": self.date,
            "subject": self.subject,
            "grade": self.grade,
            "scores": self.scores,
            "responses": self.responses,
            "total_score": self.total_score,
            "max_score": self.max_score,
            "percentage": self.percentage,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StudentAssessment:
        return cls(
            student_id=data.get("student_id", ""),
            student_name=data.get("student_name", ""),
            assessment_id=data.get("assessment_id", ""),
            date=data.get("date", ""),
            subject=data.get("subject", ""),
            grade=data.get("grade", ""),
            scores=data.get("scores", {}),
            responses=data.get("responses", []),
            total_score=data.get("total_score", 0.0),
            max_score=data.get("max_score", 100.0),
        )


@dataclass
class WeakPoint:
    """薄弱知识点。"""
    knowledge_point_id: str = ""
    knowledge_point_name: str = ""
    error_rate: float = 0.0
    affected_students: list[str] = field(default_factory=list)
    common_mistakes: list[str] = field(default_factory=list)
    suggested_remedial: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "knowledge_point_id": self.knowledge_point_id,
            "knowledge_point_name": self.knowledge_point_name,
            "error_rate": self.error_rate,
            "affected_students": self.affected_students,
            "common_mistakes": self.common_mistakes,
            "suggested_remedial": self.suggested_remedial,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WeakPoint:
        return cls(
            knowledge_point_id=data.get("knowledge_point_id", ""),
            knowledge_point_name=data.get("knowledge_point_name", ""),
            error_rate=data.get("error_rate", 0.0),
            affected_students=data.get("affected_students", []),
            common_mistakes=data.get("common_mistakes", []),
            suggested_remedial=data.get("suggested_remedial", ""),
        )


@dataclass
class ClassProfile:
    """班级学情画像。"""
    class_id: str = ""
    subject: str = ""
    grade: str = ""
    period: str = ""
    total_students: int = 0
    avg_score: float = 0.0
    score_distribution: dict[str, int] = field(default_factory=dict)
    weak_knowledge_points: list[WeakPoint] = field(default_factory=list)
    strong_knowledge_points: list[str] = field(default_factory=list)
    student_risk_levels: dict[str, str] = field(default_factory=dict)
    generated_at: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "class_id": self.class_id,
            "subject": self.subject,
            "grade": self.grade,
            "period": self.period,
            "total_students": self.total_students,
            "avg_score": self.avg_score,
            "score_distribution": self.score_distribution,
            "weak_knowledge_points": [wp.to_dict() for wp in self.weak_knowledge_points],
            "strong_knowledge_points": self.strong_knowledge_points,
            "student_risk_levels": self.student_risk_levels,
            "generated_at": self.generated_at,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ClassProfile:
        wps = [WeakPoint.from_dict(wp) for wp in data.get("weak_knowledge_points", [])]
        return cls(
            class_id=data.get("class_id", ""),
            subject=data.get("subject", ""),
            grade=data.get("grade", ""),
            period=data.get("period", ""),
            total_students=data.get("total_students", 0),
            avg_score=data.get("avg_score", 0.0),
            score_distribution=data.get("score_distribution", {}),
            weak_knowledge_points=wps,
            strong_knowledge_points=data.get("strong_knowledge_points", []),
            student_risk_levels=data.get("student_risk_levels", {}),
            generated_at=data.get("generated_at", ""),
            error=data.get("error", ""),
        )


@dataclass
class StudentProfile:
    """学生个体画像。"""
    student_id: str = ""
    name: str = ""
    grade: str = ""
    subject: str = ""
    overall_level: str = "standard"
    knowledge_mastery: dict[str, float] = field(default_factory=dict)
    learning_trend: str = "stable"
    risk_indicators: list[str] = field(default_factory=list)
    recommended_actions: list[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "student_id": self.student_id,
            "name": self.name,
            "grade": self.grade,
            "subject": self.subject,
            "overall_level": self.overall_level,
            "knowledge_mastery": self.knowledge_mastery,
            "learning_trend": self.learning_trend,
            "risk_indicators": self.risk_indicators,
            "recommended_actions": self.recommended_actions,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StudentProfile:
        return cls(
            student_id=data.get("student_id", ""),
            name=data.get("name", ""),
            grade=data.get("grade", ""),
            subject=data.get("subject", ""),
            overall_level=data.get("overall_level", "standard"),
            knowledge_mastery=data.get("knowledge_mastery", {}),
            learning_trend=data.get("learning_trend", "stable"),
            risk_indicators=data.get("risk_indicators", []),
            recommended_actions=data.get("recommended_actions", []),
            error=data.get("error", ""),
        )


@dataclass
class ErrorAnalysis:
    """错题归因分析。"""
    error_id: str = ""
    knowledge_point_id: str = ""
    error_type: str = ""
    frequency: int = 0
    sample_responses: list[str] = field(default_factory=list)
    root_cause: str = ""
    remediation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_id": self.error_id,
            "knowledge_point_id": self.knowledge_point_id,
            "error_type": self.error_type,
            "frequency": self.frequency,
            "sample_responses": self.sample_responses,
            "root_cause": self.root_cause,
            "remediation": self.remediation,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ErrorAnalysis:
        return cls(
            error_id=data.get("error_id", ""),
            knowledge_point_id=data.get("knowledge_point_id", ""),
            error_type=data.get("error_type", ""),
            frequency=data.get("frequency", 0),
            sample_responses=data.get("sample_responses", []),
            root_cause=data.get("root_cause", ""),
            remediation=data.get("remediation", ""),
        )


@dataclass
class RemedialPlan:
    """补救教学方案。"""
    student_id: str = ""
    subject: str = ""
    grade: str = ""
    weak_points: list[WeakPoint] = field(default_factory=list)
    strategies: list[str] = field(default_factory=list)
    timeline: str = ""
    exercises: list[dict[str, Any]] = field(default_factory=list)
    estimated_duration: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "student_id": self.student_id,
            "subject": self.subject,
            "grade": self.grade,
            "weak_points": [wp.to_dict() for wp in self.weak_points],
            "strategies": self.strategies,
            "timeline": self.timeline,
            "exercises": self.exercises,
            "estimated_duration": self.estimated_duration,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RemedialPlan:
        wps = [WeakPoint.from_dict(wp) for wp in data.get("weak_points", [])]
        return cls(
            student_id=data.get("student_id", ""),
            subject=data.get("subject", ""),
            grade=data.get("grade", ""),
            weak_points=wps,
            strategies=data.get("strategies", []),
            timeline=data.get("timeline", ""),
            exercises=data.get("exercises", []),
            estimated_duration=data.get("estimated_duration", ""),
            error=data.get("error", ""),
        )
