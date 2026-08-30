"""敏感词库管理。"""

from __future__ import annotations

import logging
import os
import re
import unicodedata

from .models import BYPASS_RE

logger = logging.getLogger(__name__)


def _normalize(text: str) -> str:
    return BYPASS_RE.sub("", unicodedata.normalize("NFKC", text).lower())

DEFAULT_WORDLIST_PATH = os.path.join(os.path.dirname(__file__), "data", "sensitive_words.txt")


class SensitiveWordList:
    """敏感词库 — 加载/查询/增删。"""

    def __init__(self, path: str = ""):
        self._path = path or DEFAULT_WORDLIST_PATH
        self._words: set[str] = set()
        self._matcher: re.Pattern[str] = re.compile(r"$^")
        self.load()

    def _rebuild_matcher(self) -> None:
        # SECb-P1: 单正则一次扫描, 替代 O(W×N) 逐词 in 子串
        if not self._words:
            self._matcher = re.compile(r"$^")
            return
        escaped = sorted((re.escape(w) for w in self._words), key=len, reverse=True)
        self._matcher = re.compile("|".join(escaped))

    def load(self) -> None:
        if not os.path.exists(self._path):
            logger.warning(f"敏感词库文件不存在: {self._path}")
            self._words = set()
            self._rebuild_matcher()
            return
        with open(self._path, encoding="utf-8") as f:
            lines = f.readlines()
        self._words = {
            _normalize(line.strip())
            for line in lines
            if line.strip() and not line.startswith("#")
        }
        self._words.discard("")
        self._rebuild_matcher()
        logger.info(f"敏感词库加载: {len(self._words)} 个词")

    def save(self) -> None:
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            f.write("# Fusion-K12-Teacher 敏感词库\n")
            f.write("# 格式: 每行一词，# 开头为注释\n\n")
            f.writelines(f"{word}\n" for word in sorted(self._words))
        logger.info(f"敏感词库保存: {len(self._words)} 个词")

    def add(self, word: str) -> None:
        w = _normalize(word.strip())
        if w:
            self._words.add(w)
            self._rebuild_matcher()

    def remove(self, word: str) -> None:
        self._words.discard(_normalize(word.strip()))
        self._rebuild_matcher()

    def list_words(self) -> list[str]:
        return sorted(self._words)

    def check(self, text: str) -> list[str]:
        # SECb-P1: 单正则扫描, 命中词去重保持出现顺序
        text_norm = _normalize(text)
        seen: set[str] = set()
        found: list[str] = []
        for m in self._matcher.finditer(text_norm):
            w = m.group(0)
            if w not in seen:
                seen.add(w)
                found.append(w)
        return found

    @property
    def count(self) -> int:
        return len(self._words)
