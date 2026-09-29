"""滚动窗口隔离式对话记忆 — TLive-Omni pattern 5。

MAX_TOKENS 预算, 超限自动截断最旧非 system 消息。分层 system prompt 拼接。
token 计数: 优先 tiktoken, 缺失用 char/4 估算。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

try:
    import tiktoken as _tiktoken
    _ENC = _tiktoken.get_encoding("cl100k_base")
except Exception:
    _tiktoken = None
    _ENC = None


def _count_tokens(text: str) -> int:
    if _ENC is not None:
        try:
            return len(_ENC.encode(text))
        except Exception:
            pass
    return max(1, len(text) // 4)


@dataclass
class _Msg:
    role: str
    content: str
    sticky: bool = False


@dataclass
class RollingWindowMemory:
    session_id: str = ""
    max_tokens: int = 4096
    base_prompt: str = "你是一位耐心、专业的老师。"
    persona: str = ""
    course_context: str = ""
    level: str = "B"
    _msgs: list[_Msg] = field(default_factory=list)

    def set_layers(self, *, base: str = "", persona: str = "", course_context: str = "", level: str = "") -> None:
        if base:
            self.base_prompt = base
        if persona:
            self.persona = persona
        if course_context:
            self.course_context = course_context
        if level:
            self.level = level

    def add(self, role: str, text: str, *, sticky: bool = False) -> None:
        self._msgs.append(_Msg(role=role, content=text, sticky=sticky))
        self._truncate()
        logger.debug("memory[%s]: add role=%s tokens~=%d total_msgs=%d",
                     self.session_id, role, _count_tokens(text), len(self._msgs))

    def add_rag(self, snippet: str) -> None:
        if snippet:
            self._msgs.append(_Msg(role="system", content=f"[知识补充] {snippet}", sticky=True))

    def _truncate(self) -> None:
        budget = self.max_tokens
        while self._total_tokens() > budget and len(self._msgs) > 1:
            for i, m in enumerate(self._msgs):
                if not m.sticky and m.role != "system":
                    logger.debug("memory[%s]: 截断旧消息 role=%s", self.session_id, m.role)
                    self._msgs.pop(i)
                    break
            else:
                break

    def _total_tokens(self) -> int:
        return sum(_count_tokens(m.content) for m in self._msgs) + _count_tokens(self.build_system_prompt())

    def build_system_prompt(self) -> str:
        parts = [self.base_prompt]
        if self.course_context:
            parts.append(f"\n[课程上下文]\n{self.course_context}")
        if self.persona:
            parts.append(f"\n[人设]\n{self.persona}")
        parts.append(f"\n[分层] {self.level}")
        return "\n".join(parts)

    def build_messages(self) -> list[dict[str, str]]:
        msgs: list[dict[str, str]] = [{"role": "system", "content": self.build_system_prompt()}]
        msgs.extend({"role": m.role, "content": m.content} for m in self._msgs if m.role != "system" or m.sticky)
        return msgs

    def clear(self) -> None:
        self._msgs.clear()
