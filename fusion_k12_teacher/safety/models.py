# Safety module data models.

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .._coerce import coerce_str, coerce_str_list

# SEC-7/SEC-8: unified separator bypass character class.
# Previously wordlist/age_checker/filter had three divergent regexes; filter missed BOM, and all
# three missed comma/semicolon/colon/exclamation/soft hyphen/full-width/dashes —
# i18n: user-facing
# e.g. "杀,人" "杀;人" could bypass sensitive-word detection.
BYPASS_SEPARATORS = (
    r"\s"
    r"﻿"      # BOM
    r"​"      # ZWSP
    r"‌"      # ZWNJ
    r"‍"      # ZWJ
    r"⁠"      # WJ
    r"­"      # soft hyphen
    r".．。、・"     # dot + ideographic comma + middle dot
    r"\-–—−"       # hyphen/dash variants
    r"_/|"
    r",;:!，；：！"  # punctuation separators (half-width + full-width)
)
# Single separator: used by wordlist/age_checker normalization
BYPASS_RE = re.compile(f"[{BYPASS_SEPARATORS}]")
# Between-word separator (0..N): used by filter._bypass_pattern
BYPASS_CLASS = f"[{BYPASS_SEPARATORS}]*"


# Content check result.
@dataclass
class ContentCheckResult:

    is_safe: bool = True
    risk_level: str = "safe"
    flagged_words: list[str] = field(default_factory=list)
    age_issues: list[str] = field(default_factory=list)
    filtered_text: str = ""
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        decision = "allow" if self.is_safe else "block"
        filtered = self.filtered_text if not self.is_safe and self.filtered_text else ""
        return {
            "is_safe": self.is_safe,
            "decision": decision,
            "risk_level": self.risk_level,
            "flagged_words": self.flagged_words,
            "age_issues": self.age_issues,
            "filtered_text": self.filtered_text,
            "forced_filtered_text": filtered,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ContentCheckResult:
        return cls(
            is_safe=d.get("is_safe", True),
            risk_level=coerce_str(d.get("risk_level", "safe")),
            flagged_words=coerce_str_list(d.get("flagged_words", [])),
            age_issues=coerce_str_list(d.get("age_issues", [])),
            filtered_text=coerce_str(d.get("filtered_text", "")),
            summary=coerce_str(d.get("summary", "")),
        )


# Age rating configuration.
@dataclass
class AgeRating:

    grade: str = ""
    max_abstraction: str = "concrete"
    allowed_topics: list[str] = field(default_factory=list)
    restricted_topics: list[str] = field(default_factory=list)
    # i18n: user-facing
    vocabulary_level: str = "基础"

    def to_dict(self) -> dict[str, Any]:
        return {
            "grade": self.grade,
            "max_abstraction": self.max_abstraction,
            "allowed_topics": self.allowed_topics,
            "restricted_topics": self.restricted_topics,
            "vocabulary_level": self.vocabulary_level,
        }


# Filter level configuration.
@dataclass
class FilterLevel:

    level: str = "standard"
    sensitive_words: bool = True
    age_check: bool = True
    output_check: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "sensitive_words": self.sensitive_words,
            "age_check": self.age_check,
            "output_check": self.output_check,
        }
