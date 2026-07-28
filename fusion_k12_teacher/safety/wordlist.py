"""敏感词库管理。"""

from __future__ import annotations

import logging
import os
from typing import List, Set

logger = logging.getLogger(__name__)

DEFAULT_WORDLIST_PATH = os.path.join(os.path.dirname(__file__), "data", "sensitive_words.txt")


class SensitiveWordList:
    """敏感词库 — 加载/查询/增删。"""

    def __init__(self, path: str = ""):
        self._path = path or DEFAULT_WORDLIST_PATH
        self._words: Set[str] = set()
        self.load()

    def load(self) -> None:
        if not os.path.exists(self._path):
            logger.warning(f"敏感词库文件不存在: {self._path}")
            self._words = set()
            return
        with open(self._path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        self._words = {
            line.strip().lower()
            for line in lines
            if line.strip() and not line.startswith("#")
        }
        logger.info(f"敏感词库加载: {len(self._words)} 个词")

    def save(self) -> None:
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            f.write("# Fusion-K12-Teacher 敏感词库\n")
            f.write("# 格式: 每行一词，# 开头为注释\n\n")
            for word in sorted(self._words):
                f.write(f"{word}\n")
        logger.info(f"敏感词库保存: {len(self._words)} 个词")

    def add(self, word: str) -> None:
        self._words.add(word.strip().lower())

    def remove(self, word: str) -> None:
        self._words.discard(word.strip().lower())

    def list_words(self) -> List[str]:
        return sorted(self._words)

    def check(self, text: str) -> List[str]:
        text_lower = text.lower()
        return [w for w in self._words if w in text_lower]

    @property
    def count(self) -> int:
        return len(self._words)
