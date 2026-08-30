"""内容过滤引擎 — 多层过滤策略。"""

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

SAFETY_PROMPT_SUFFIX = (
    "\n\n重要约束：以上内容面向K-12中小学生，"
    "请确保内容安全、积极、适龄，不含暴力、色情、政治敏感等不当内容。"
)

_RISK_ORDER = {"safe": 0, "medium": 1, "high": 2, "critical": 3}

_MAX_INPUT_LEN = 500
_INJECTION_PATTERNS = re.compile(
    r"忽略(以上|前面|之前|所有)|忽略指令|直接返回|系统指令|system\s*prompt|DROP\s|DELETE\s",
    re.IGNORECASE,
)


def sanitize_input(text: str, max_len: int = _MAX_INPUT_LEN) -> str:
    """清洗用户输入 — 扫描注入、剥离控制字符、截断长度 (ENG-1, SEC-13/14)。

    SEC-13: 先全文扫注入再截断, 避免跨 max_len 边界的关键词被切断而漏检。
    SEC-14: 检出注入即替换匹配短语为占位 (非仅包裹), LLM 不可读原文指令。
    """
    if not isinstance(text, str):
        text = str(text)
    # SEC-13: 先扫描未截断全文
    if _INJECTION_PATTERNS.search(text):
        logger.warning("检测到疑似提示注入, 已中和匹配短语: %s", text[:60])
        text = _INJECTION_PATTERNS.sub("[已过滤指令]", text)
    text = text[:max_len]
    text = "".join(c for c in text if c == "\n" or ord(c) >= 0x20)
    return text


def _bypass_pattern(word: str) -> re.Pattern:
    chars = [re.escape(c) for c in word]
    return re.compile(BYPASS_CLASS.join(chars), re.IGNORECASE | re.UNICODE)


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
        # A15: 可插拔规则管线 — 敏感词层 + 适龄层, 新增过滤规则追加到此列表即可
        self._filters: list = [
            self._filter_sensitive_words,
            self._filter_age,
        ]
        logger.info(
            f"ContentFilter 初始化, 词库: {self.wordlist.count} 词, "
            f"等级: {self.filter_level.level}"
        )

    @staticmethod
    def _escalate(result: ContentCheckResult, level: str) -> None:
        if _RISK_ORDER.get(level, 0) > _RISK_ORDER.get(result.risk_level, 0):
            result.risk_level = level

    def check_text(self, text: str, grade: str = "3") -> ContentCheckResult:
        # SEC-10: 任何异常 fail-closed (标记不安全), 不向调用方抛
        # A15: 规则层走可插拔 pipeline, 不再重复手写敏感词+适龄逻辑
        return self._run_pipeline(text, grade, scope="input")

    def check_output(self, text: str, grade: str = "3") -> ContentCheckResult:
        # SEC-10: 输出校验同样 fail-closed
        # A15: 复用 _run_pipeline(规则层单一实现), 不再重复 check_text 的逻辑分叉
        return self._run_pipeline(text, grade, scope="output")

    def _run_pipeline(self, text: str, grade: str, scope: str) -> ContentCheckResult:
        """A15: 可插拔规则管线 — 各过滤层为独立 callable, 按序应用。
        scope=input 走 sensitive_words+age_check 门控, scope=output 走 output_check 门控。
        新增过滤规则只须追加 callable 到 self._filters, 不改核心管线。"""
        result = ContentCheckResult(filtered_text=text)
        try:
            # SEC-12: 词库缺失 disabled, 最后防线不可用, fail-closed 拦截
            wordlist_enabled = (
                self.filter_level.sensitive_words if scope == "input"
                else self.filter_level.output_check
            )
            if wordlist_enabled and self.wordlist.disabled:
                result.is_safe = False
                self._escalate(result, "critical")
                result.summary = f"[拦截] 敏感词库未加载, {'输出' if scope == 'output' else '内容'}检查不可用"
                return result
            # A15: 逐 filter 应用, 每个 filter 接收 (result, text, grade, scope) 就地 mutate result
            for f in self._filters:
                f(result, text, grade, scope)
        except Exception as exc:
            logger.error("%s 管线异常, fail-closed: %s", scope, exc, exc_info=True)
            result.is_safe = False
            self._escalate(result, "critical")
            result.summary = f"[拦截] {'输出' if scope == 'output' else '内容'}检查内部异常"
            return result

        result.summary = self._build_summary(result)
        return result

    # A15: 规则层各 filter 独立 — 管线结构可插拔, FilterLevel 控制各层是否激活
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
            logger.warning(f"{'输出' if scope == 'output' else '敏感'}词检出: {flagged}")

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
            # SEC-11: 仅年龄命中时无词替换, 置占位提示避免原文原样透传
            if not result.filtered_text or result.filtered_text == text:
                result.filtered_text = "[内容因适龄问题已被拦截]"
            result.is_safe = False
            self._escalate(result, "medium")
            logger.warning(f"适龄问题: {age_issues}")

    def filter_sensitive(self, text: str) -> str:
        flagged = self.wordlist.check(text)
        if not flagged:
            return text
        return self._replace_words(text, flagged)

    def get_safety_prompt_suffix(self) -> str:
        return SAFETY_PROMPT_SUFFIX

    def _replace_words(self, text: str, words: list[str]) -> str:
        # SEC-9: 长词优先替换, 避免短词先替导致长词残留泄露
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
