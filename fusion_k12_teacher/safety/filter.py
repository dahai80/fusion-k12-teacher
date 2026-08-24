"""内容过滤引擎 — 多层过滤策略。"""

from __future__ import annotations

import logging
import re
import unicodedata

from .age_checker import AgeChecker
from .models import ContentCheckResult, FilterLevel
from .wordlist import SensitiveWordList

logger = logging.getLogger(__name__)

DEFAULT_FILTER_LEVEL = FilterLevel(
    level="standard",
    sensitive_words=True,
    age_check=True,
    output_check=True,
)

REPLACEMENT = "**"

SAFETY_PROMPT_SUFFIX = (
    "\n\n重要约束：以上内容面向K-12中小学生，"
    "请确保内容安全、积极、适龄，不含暴力、色情、政治敏感等不当内容。"
)

_RISK_ORDER = {"safe": 0, "medium": 1, "high": 2, "critical": 3}

_BYPASS_CLASS = r"[\s​-‍⁠･・\-_]*"


def _bypass_pattern(word: str) -> re.Pattern:
    chars = [re.escape(c) for c in word]
    return re.compile(_BYPASS_CLASS.join(chars), re.IGNORECASE | re.UNICODE)


class ContentFilter:
    """内容过滤器 — 敏感词 + 适龄 + 输出校验。"""

    def __init__(
        self,
        wordlist: SensitiveWordList | None = None,
        age_checker: AgeChecker | None = None,
        mlx=None,
        filter_level: FilterLevel | None = None,
    ):
        self.wordlist = wordlist or SensitiveWordList()
        self.age_checker = age_checker or AgeChecker()
        self.mlx = mlx
        self.filter_level = filter_level or DEFAULT_FILTER_LEVEL
        logger.info(
            f"ContentFilter 初始化, 词库: {self.wordlist.count} 词, "
            f"等级: {self.filter_level.level}"
        )

    @staticmethod
    def _escalate(result: ContentCheckResult, level: str) -> None:
        if _RISK_ORDER.get(level, 0) > _RISK_ORDER.get(result.risk_level, 0):
            result.risk_level = level

    def check_text(self, text: str, grade: str = "3") -> ContentCheckResult:
        result = ContentCheckResult(filtered_text=text)

        if self.filter_level.sensitive_words:
            flagged = self.wordlist.check(text)
            if flagged:
                result.flagged_words = flagged
                result.filtered_text = self._replace_words(text, flagged)
                result.is_safe = False
                self._escalate(result, "high")
                logger.warning(f"敏感词检出: {flagged}")

        if self.filter_level.age_check:
            age_issues = self.age_checker.check_content(text, grade)
            if age_issues:
                result.age_issues = age_issues
                result.is_safe = False
                self._escalate(result, "medium")
                logger.warning(f"适龄问题: {age_issues}")

        result.summary = self._build_summary(result)
        return result

    def check_output(self, text: str, grade: str = "3") -> ContentCheckResult:
        result = ContentCheckResult(filtered_text=text)

        if self.filter_level.output_check:
            flagged = self.wordlist.check(text)
            if flagged:
                result.flagged_words = flagged
                result.filtered_text = self._replace_words(text, flagged)
                result.is_safe = False
                self._escalate(result, "high")
                logger.warning(f"输出敏感词检出: {flagged}")

            age_issues = self.age_checker.check_content(text, grade)
            if age_issues:
                result.age_issues = age_issues
                result.is_safe = False
                self._escalate(result, "medium")
                logger.warning(f"输出适龄问题: {age_issues}")

        result.summary = self._build_summary(result)
        return result

    def filter_sensitive(self, text: str) -> str:
        flagged = self.wordlist.check(text)
        if not flagged:
            return text
        return self._replace_words(text, flagged)

    def get_safety_prompt_suffix(self) -> str:
        return SAFETY_PROMPT_SUFFIX

    def _replace_words(self, text: str, words: list[str]) -> str:
        result = text
        for w in words:
            if not w:
                continue
            pattern = _bypass_pattern(w)
            result = pattern.sub(REPLACEMENT * len(w), result)
        return result

    def _build_summary(self, result: ContentCheckResult) -> str:
        parts = []
        if result.flagged_words:
            parts.append(f"敏感词: {', '.join(result.flagged_words)}")
        if result.age_issues:
            parts.append(f"适龄问题: {'; '.join(result.age_issues)}")
        if not parts:
            parts.append("内容安全")
        status = "安全" if result.is_safe else "不安全"
        return f"[{status}] {' | '.join(parts)}"

    def _strip_json(self, text: str) -> str:
        text = unicodedata.normalize("NFKC", text).strip()
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return match.group(0)
        if text.startswith("```"):
            lines = text.split("\n")
            if len(lines) >= 2:
                text = "\n".join(lines[1:])
                if text.rstrip().endswith("```"):
                    text = text.rstrip()[:-3]
        return text.strip()
