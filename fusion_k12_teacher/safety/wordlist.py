# Sensitive word list management.

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


# Sensitive word list — load/query/add/remove.
class SensitiveWordList:

    def __init__(self, path: str = ""):
        self._path = path or DEFAULT_WORDLIST_PATH
        self._words: set[str] = set()
        self._matcher: re.Pattern[str] = re.compile(r"$^")
        # SEC-12: missing wordlist marks disabled; ContentFilter fails closed, no silent pass-through
        self.disabled: bool = False
        self.load()

    def _rebuild_matcher(self) -> None:
        # SECb-P1: single regex one-pass scan, replaces O(W×N) per-word `in` substring checks
        # SEC-23: local build; assign only if compile succeeds, on failure keep old matcher without polluting _words state
        # E16: full recompile — only load (first/batch) and remove (cannot incrementally strip a word) call this.
        # add goes through _extend_matcher incremental concat, no full alternation recompile.
        if not self._words:
            self._matcher = re.compile(r"$^")
            return
        try:
            escaped = sorted((re.escape(w) for w in self._words), key=len, reverse=True)
            new_matcher = re.compile("|".join(escaped))
        except re.error as e:
            logger.error("Sensitive-word matcher build failed, keeping old matcher: %s", e)
            raise
        self._matcher = new_matcher

    # E16: incremental concat — only escape+concat the new word, no full alternation recompile.
    #         O(1) per word instead of O(W). Failure raises re.error for the caller to roll back _words.
    def _extend_matcher(self, word: str) -> None:
        if not self._words:
            self._matcher = re.compile(r"$^")
            return
        try:
            new_part = re.escape(word)
            # Old matcher is already an alternation; just | concat the new word
            new_matcher = re.compile(self._matcher.pattern + "|" + new_part)
        except re.error as e:
            logger.error("Sensitive-word matcher incremental build failed: %s", e)
            raise
        self._matcher = new_matcher

    def load(self) -> None:
        if not os.path.exists(self._path):
            logger.warning(f"Sensitive wordlist file missing, marking disabled, filter will fail closed: {self._path}")
            self._words = set()
            self.disabled = True
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
        self.disabled = False
        self._rebuild_matcher()
        logger.info(f"Sensitive wordlist loaded: {len(self._words)} words")

    def save(self) -> None:
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            # i18n: user-facing (data-file header for the Chinese blocklist)
            f.write("# Fusion-K12-Teacher 敏感词库\n")
            f.write("# 格式: 每行一词，# 开头为注释\n\n")
            f.writelines(f"{word}\n" for word in sorted(self._words))
        logger.info(f"Sensitive wordlist saved: {len(self._words)} words")

    def add(self, word: str) -> None:
        w = _normalize(word.strip())
        if not w:
            return
        self._words.add(w)
        # SEC-23: roll back the added word when matcher build fails, no silent missing state
        # E16: incremental concat instead of full recompile — words already in _words are not re-escaped
        try:
            self._extend_matcher(w)
        except re.error:
            logger.error("New word %r broke matcher build, rolled back", w)
            self._words.discard(w)
            self._rebuild_matcher()

    def remove(self, word: str) -> None:
        self._words.discard(_normalize(word.strip()))
        self._rebuild_matcher()

    def list_words(self) -> list[str]:
        return sorted(self._words)

    def check(self, text: str) -> list[str]:
        # SECb-P1: single regex scan, dedupe hits preserving order of appearance
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
