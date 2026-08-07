"""安全模块数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ContentCheckResult:
    """内容检查结果。"""

    is_safe: bool = True
    risk_level: str = "safe"
    flagged_words: list[str] = field(default_factory=list)
    age_issues: list[str] = field(default_factory=list)
    llm_issues: list[str] = field(default_factory=list)
    filtered_text: str = ""
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_safe": self.is_safe,
            "risk_level": self.risk_level,
            "flagged_words": self.flagged_words,
            "age_issues": self.age_issues,
            "llm_issues": self.llm_issues,
            "filtered_text": self.filtered_text,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ContentCheckResult:
        return cls(
            is_safe=d.get("is_safe", True),
            risk_level=d.get("risk_level", "safe"),
            flagged_words=d.get("flagged_words", []),
            age_issues=d.get("age_issues", []),
            llm_issues=d.get("llm_issues", []),
            filtered_text=d.get("filtered_text", ""),
            summary=d.get("summary", ""),
        )


@dataclass
class AgeRating:
    """适龄等级配置。"""

    grade: str = ""
    max_abstraction: str = "concrete"
    allowed_topics: list[str] = field(default_factory=list)
    restricted_topics: list[str] = field(default_factory=list)
    vocabulary_level: str = "基础"

    def to_dict(self) -> dict[str, Any]:
        return {
            "grade": self.grade,
            "max_abstraction": self.max_abstraction,
            "allowed_topics": self.allowed_topics,
            "restricted_topics": self.restricted_topics,
            "vocabulary_level": self.vocabulary_level,
        }


@dataclass
class FilterLevel:
    """过滤等级配置。"""

    level: str = "standard"
    sensitive_words: bool = True
    age_check: bool = True
    llm_review: bool = False
    output_check: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "sensitive_words": self.sensitive_words,
            "age_check": self.age_check,
            "llm_review": self.llm_review,
            "output_check": self.output_check,
        }
