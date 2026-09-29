"""emotion_tag 解析广播日志过滤 — TLive-Omni pattern 4。

正则剥离 [tag] -> TTS 语速 + Avatar 表情。未知 tag -> neutral。
日志过滤器: 记录前剥离 tag, 不污染日志。
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"\s*\[([a-z_-]+)\]\s*$")

EMOTION_SPEED: dict[str, float] = {
    "happy": 1.05, "curious": 1.03, "encouraging": 1.02,
    "neutral": 1.0, "thinking": 0.95, "focused": 1.0, "reflective": 0.97,
}

EMOTION_AVATAR_EXPR: dict[str, str] = {
    "happy": "smile", "curious": "raised_brow", "encouraging": "warm",
    "neutral": "neutral", "thinking": "thoughtful", "focused": "focused",
    "reflective": "calm",
}

_DEFAULT_TAG = "neutral"


class EmotionTagParser:
    def __init__(self, session_id: str = "") -> None:
        self.session_id = session_id

    def strip(self, text: str) -> tuple[str, str]:
        if not text:
            return "", _DEFAULT_TAG
        m = _TAG_RE.search(text)
        if m is None:
            return text, _DEFAULT_TAG
        tag = m.group(1)
        if tag not in EMOTION_SPEED:
            logger.debug("emotion[%s]: 未知 tag %s -> neutral", self.session_id, tag)
            tag = _DEFAULT_TAG
        return _TAG_RE.sub("", text).rstrip(), tag

    def speed_for(self, tag: str) -> float:
        return EMOTION_SPEED.get(tag, 1.0)

    def expr_for(self, tag: str) -> str:
        return EMOTION_AVATAR_EXPR.get(tag, "neutral")

    async def broadcast(
        self, tag: str,
        tts_cb: Callable[[str, float], Awaitable[None] | None] | None = None,
        avatar_cb: Callable[[str], Awaitable[None] | None] | None = None,
    ) -> None:
        speed = self.speed_for(tag)
        expr = self.expr_for(tag)
        logger.debug("emotion[%s]: broadcast tag=%s speed=%.2f expr=%s", self.session_id, tag, speed, expr)
        if tts_cb is not None:
            res = tts_cb(tag, speed)
            if res is not None:
                await res
        if avatar_cb is not None:
            res = avatar_cb(expr)
            if res is not None:
                await res


class EmotionLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str):
                record.msg = _TAG_RE.sub("", record.msg)
        except Exception:
            pass
        return True
