"""内容过滤引擎 — 多层过滤策略。"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from .models import ContentCheckResult, FilterLevel
from .wordlist import SensitiveWordList
from .age_checker import AgeChecker

logger = logging.getLogger(__name__)

DEFAULT_FILTER_LEVEL = FilterLevel(
    level="standard",
    sensitive_words=True,
    age_check=True,
    llm_review=False,
    output_check=True,
)

REPLACEMENT = "**"

SAFETY_PROMPT_SUFFIX = (
    "\n\n重要约束：以上内容面向K-12中小学生，"
    "请确保内容安全、积极、适龄，不含暴力、色情、政治敏感等不当内容。"
)


class ContentFilter:
    """内容过滤器 — 敏感词 + 适龄 + LLM自审查 + 输出校验。"""

    def __init__(
        self,
        wordlist: Optional[SensitiveWordList] = None,
        age_checker: Optional[AgeChecker] = None,
        mlx=None,
        filter_level: Optional[FilterLevel] = None,
    ):
        self.wordlist = wordlist or SensitiveWordList()
        self.age_checker = age_checker or AgeChecker()
        self.mlx = mlx
        self.filter_level = filter_level or DEFAULT_FILTER_LEVEL
        logger.info(f"ContentFilter 初始化, 词库: {self.wordlist.count} 词, 等级: {self.filter_level.level}")

    def check_text(self, text: str, grade: str = "3") -> ContentCheckResult:
        """完整内容检查（输入侧）。"""
        result = ContentCheckResult(filtered_text=text)

        if self.filter_level.sensitive_words:
            flagged = self.wordlist.check(text)
            if flagged:
                result.flagged_words = flagged
                result.filtered_text = self._replace_words(text, flagged)
                result.is_safe = False
                result.risk_level = "high"
                logger.warning(f"敏感词检出: {flagged}")

        if self.filter_level.age_check:
            age_issues = self.age_checker.check_content(text, grade)
            if age_issues:
                result.age_issues = age_issues
                result.is_safe = False
                if result.risk_level == "safe":
                    result.risk_level = "medium"
                logger.warning(f"适龄问题: {age_issues}")

        result.summary = self._build_summary(result)
        return result

    def check_output(self, text: str, grade: str = "3") -> ContentCheckResult:
        """输出侧二次检查。"""
        result = ContentCheckResult(filtered_text=text)

        if self.filter_level.output_check:
            flagged = self.wordlist.check(text)
            if flagged:
                result.flagged_words = flagged
                result.filtered_text = self._replace_words(text, flagged)
                result.is_safe = False
                result.risk_level = "high"

            age_issues = self.age_checker.check_content(text, grade)
            if age_issues:
                result.age_issues = age_issues
                result.is_safe = False
                if result.risk_level == "safe":
                    result.risk_level = "medium"

        result.summary = self._build_summary(result)
        return result

    async def llm_review(self, text: str, grade: str = "3") -> ContentCheckResult:
        """LLM 自审查 — 通过模型判断内容是否安全。"""
        if not self.mlx:
            return ContentCheckResult(
                is_safe=True, filtered_text=text, summary="LLM审查不可用，跳过"
            )

        try:
            prompt = (
                f"请审查以下面向{grade}年级K-12学生的内容是否安全、适龄。"
                f"如有不当内容，请列出问题并返回JSON: "
                f'{{"safe": true/false, "issues": ["问题1", ...]}}\n\n内容:\n{text}'
            )
            resp = await self.mlx.chat(prompt, temperature=0.1)
            import json
            data = json.loads(self._strip_json(resp))
            issues = data.get("issues", [])
            return ContentCheckResult(
                is_safe=data.get("safe", True),
                risk_level="medium" if issues else "safe",
                llm_issues=issues,
                filtered_text=text,
                summary="; ".join(issues) if issues else "LLM审查通过",
            )
        except Exception as e:
            logger.error(f"LLM审查失败: {e}")
            return ContentCheckResult(
                is_safe=True, filtered_text=text, summary=f"LLM审查异常: {e}"
            )

    def filter_sensitive(self, text: str) -> str:
        """仅执行敏感词替换。"""
        flagged = self.wordlist.check(text)
        if not flagged:
            return text
        return self._replace_words(text, flagged)

    def get_safety_prompt_suffix(self) -> str:
        return SAFETY_PROMPT_SUFFIX

    def _replace_words(self, text: str, words: List[str]) -> str:
        result = text
        for w in words:
            pattern = re.compile(re.escape(w), re.IGNORECASE)
            result = pattern.sub(REPLACEMENT * len(w), result)
        return result

    def _build_summary(self, result: ContentCheckResult) -> str:
        parts = []
        if result.flagged_words:
            parts.append(f"敏感词: {', '.join(result.flagged_words)}")
        if result.age_issues:
            parts.append(f"适龄问题: {'; '.join(result.age_issues)}")
        if result.llm_issues:
            parts.append(f"LLM问题: {'; '.join(result.llm_issues)}")
        if not parts:
            parts.append("内容安全")
        status = "安全" if result.is_safe else "不安全"
        return f"[{status}] {' | '.join(parts)}"

    def _strip_json(self, text: str) -> str:
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1])
        return text.strip()
