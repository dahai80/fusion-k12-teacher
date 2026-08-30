"""安全模块数据模型。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .._coerce import coerce_str, coerce_str_list

# SEC-7/SEC-8: 统一分隔符绕过字符类。
# 之前 wordlist/age_checker/filter 三处正则分叉, filter 漏 BOM, 三处均漏
# 逗号/分号/冒号/感叹号/软连字符/全角/破折号, "杀,人" "杀;人" 可绕过敏感词检测。
BYPASS_SEPARATORS = (
    r"\s"
    r"﻿"      # BOM
    r"​"      # ZWSP
    r"‌"      # ZWNJ
    r"‍"      # ZWJ
    r"⁠"      # WJ
    r"­"      # soft hyphen
    r".．。、・"     # 点号 + 中式逗号 + 中点
    r"\-–—−"       # 连字符/破折号
    r"_/|"
    r",;:!，；：！"  # 标点分隔符 (半角 + 全角)
)
# 单分隔符: wordlist/age_checker 归一化用
BYPASS_RE = re.compile(f"[{BYPASS_SEPARATORS}]")
# 词间分隔符 (0..N): filter._bypass_pattern 用
BYPASS_CLASS = f"[{BYPASS_SEPARATORS}]*"


@dataclass
class ContentCheckResult:
    """内容检查结果。"""

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
    output_check: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "sensitive_words": self.sensitive_words,
            "age_check": self.age_check,
            "output_check": self.output_check,
        }
