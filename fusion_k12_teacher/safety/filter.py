# Content filter engine — multi-layer filtering strategy.

from __future__ import annotations

import logging
import re
import unicodedata

from .age_checker import AgeChecker
from .models import BYPASS_CLASS, ContentCheckResult, FilterLevel
from .wordlist import SensitiveWordList

logger = logging.getLogger(__name__)

DEFAULT_FILTER_LEVEL = FilterLevel(
    level="standard",
    sensitive_words=True,
    age_check=True,
    output_check=True,
)

REPLACEMENT = "**"

# i18n: user-facing (LLM prompt text appended to Chinese teaching prompts)
SAFETY_PROMPT_SUFFIX = (
    "\n\n重要约束：以上内容面向K-12中小学生，"
    "请确保内容安全、积极、适龄，不含暴力、色情、政治敏感等不当内容。"
)

_RISK_ORDER = {"safe": 0, "medium": 1, "high": 2, "critical": 3}

_MAX_INPUT_LEN = 500
# i18n: user-facing (Chinese prompt-injection detection phrases, functional data)
_INJECTION_PATTERNS = re.compile(
    r"忽略(以上|前面|之前|所有)|忽略指令|直接返回|系统指令|system\s*prompt|DROP\s|DELETE\s",
    re.IGNORECASE,
)


# Sanitizes user input — scans injection, strips control chars, truncates length (ENG-1, SEC-13/14).
#
#     SEC-13: scan the full text for injection before truncating, so keywords crossing the max_len
#     boundary are not cut and missed.
#     SEC-14: on detection, replace matched phrases with a placeholder (not just wrap), so the LLM
#     cannot read the original instructions.
def sanitize_input(text: str, max_len: int = _MAX_INPUT_LEN) -> str:
    if not isinstance(text, str):
        text = str(text)
    # SEC-13: scan the full untruncated text first
    if _INJECTION_PATTERNS.search(text):
        logger.warning("suspected prompt injection detected, matched phrases neutralized: %s", text[:60])
        # i18n: user-facing (neutralization placeholder embedded into Chinese user input)
        text = _INJECTION_PATTERNS.sub("[已过滤指令]", text)
    text = text[:max_len]
    text = "".join(c for c in text if c == "\n" or ord(c) >= 0x20)
    return text


def _bypass_pattern(word: str) -> re.Pattern:
    chars = [re.escape(c) for c in word]
    return re.compile(BYPASS_CLASS.join(chars), re.IGNORECASE | re.UNICODE)


# Content filter — sensitive words + age appropriateness + output verification.
class ContentFilter:

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
        # A15: pluggable rule pipeline — sensitive-word layer + age layer; append new filter rules to this list
        self._filters: list = [
            self._filter_sensitive_words,
            self._filter_age,
        ]
        logger.info(
            f"ContentFilter initialized, wordlist: {self.wordlist.count} words, "
            f"level: {self.filter_level.level}"
        )

    @staticmethod
    def _escalate(result: ContentCheckResult, level: str) -> None:
        if _RISK_ORDER.get(level, 0) > _RISK_ORDER.get(result.risk_level, 0):
            result.risk_level = level

    def check_text(self, text: str, grade: str = "3") -> ContentCheckResult:
        # SEC-10: any exception fails closed (marked unsafe), never raised to the caller
        # A15: rule layers go through the pluggable pipeline, no duplicated hand-written sensitive-word+age logic
        return self._run_pipeline(text, grade, scope="input")

    def check_output(self, text: str, grade: str = "3") -> ContentCheckResult:
        # SEC-10: output verification also fails closed
        # A15: reuses _run_pipeline (single rule-layer implementation), no duplicated check_text logic fork
        return self._run_pipeline(text, grade, scope="output")

    # A15: pluggable rule pipeline — each filter layer is an independent callable, applied in order.
    #         scope=input is gated by sensitive_words+age_check, scope=output by output_check.
    #         New filter rules only need to append a callable to self._filters, core pipeline unchanged.
    def _run_pipeline(self, text: str, grade: str, scope: str) -> ContentCheckResult:
        result = ContentCheckResult(filtered_text=text)
        try:
            # SEC-12: wordlist missing/disabled means the last line of defense is down, fail-closed block
            wordlist_enabled = (
                self.filter_level.sensitive_words if scope == "input"
                else self.filter_level.output_check
            )
            if wordlist_enabled and self.wordlist.disabled:
                result.is_safe = False
                self._escalate(result, "critical")
                result.summary = f"[blocked] wordlist not loaded, {'output' if scope == 'output' else 'content'} check unavailable"
                return result
            # A15: apply filters one by one; each filter receives (result, text, grade, scope) and mutates result in place
            for f in self._filters:
                f(result, text, grade, scope)
        except Exception as exc:
            logger.error("%s pipeline error, fail-closed: %s", scope, exc, exc_info=True)
            result.is_safe = False
            self._escalate(result, "critical")
            result.summary = f"[blocked] {'output' if scope == 'output' else 'content'} check internal error"
            return result

        result.summary = self._build_summary(result)
        return result

    # A15: rule-layer filters are independent — pluggable pipeline structure, FilterLevel controls which layers activate
    def _filter_sensitive_words(self, result, text, grade, scope) -> None:
        enabled = (
            self.filter_level.sensitive_words if scope == "input"
            else self.filter_level.output_check
        )
        if not enabled:
            return
        flagged = self.wordlist.check(text)
        if flagged:
            result.flagged_words = flagged
            result.filtered_text = self._replace_words(text, flagged)
            result.is_safe = False
            self._escalate(result, "high")
            logger.warning(f"{'output' if scope == 'output' else 'sensitive'} word detected: {flagged}")

    def _filter_age(self, result, text, grade, scope) -> None:
        enabled = (
            self.filter_level.age_check if scope == "input"
            else self.filter_level.output_check
        )
        if not enabled:
            return
        age_issues = self.age_checker.check_content(text, grade)
        if age_issues:
            result.age_issues = age_issues
            # SEC-11: age-only hits have no word replacement; set a placeholder to avoid passing the original text through
            if not result.filtered_text or result.filtered_text == text:
                # i18n: user-facing (blocked-content placeholder surfaced to teachers)
                result.filtered_text = "[内容因适龄问题已被拦截]"
            result.is_safe = False
            self._escalate(result, "medium")
            logger.warning(f"age-appropriateness issues: {age_issues}")

    def filter_sensitive(self, text: str) -> str:
        flagged = self.wordlist.check(text)
        if not flagged:
            return text
        return self._replace_words(text, flagged)

    def get_safety_prompt_suffix(self) -> str:
        return SAFETY_PROMPT_SUFFIX

    def _replace_words(self, text: str, words: list[str]) -> str:
        # SEC-9: replace longest words first, so short-word-first replacement cannot leave long-word residue leaking
        result = text
        for w in sorted(words, key=len, reverse=True):
            if not w:
                continue
            pattern = _bypass_pattern(w)
            result = pattern.sub(REPLACEMENT * len(w), result)
        return result

    def _build_summary(self, result: ContentCheckResult) -> str:
        parts = []
        if result.flagged_words:
            parts.append(f"sensitive words: {', '.join(result.flagged_words)}")
        if result.age_issues:
            parts.append(f"age issues: {'; '.join(result.age_issues)}")
        if not parts:
            parts.append("content safe")
        status = "safe" if result.is_safe else "unsafe"
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
