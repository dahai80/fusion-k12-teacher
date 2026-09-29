"""FSM 五态状态机 — TLive-Omni pattern 1。

IDLE/USER_SPEAKING/AI_THINKING/AI_SPEAKING/ERROR + 统一钩子。
ERROR 态自动触发 BargeInBus 清场。所有转换结构化日志 (不含 emotion tag)。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .barge_in import BargeInBus


class SessionState(StrEnum):
    IDLE = "idle"
    USER_SPEAKING = "user_speaking"
    AI_THINKING = "ai_thinking"
    AI_SPEAKING = "ai_speaking"
    ERROR = "error"


_ALLOWED: dict[SessionState, frozenset[SessionState]] = {
    SessionState.IDLE: frozenset({SessionState.USER_SPEAKING, SessionState.AI_THINKING, SessionState.ERROR}),
    SessionState.USER_SPEAKING: frozenset({SessionState.AI_THINKING, SessionState.IDLE, SessionState.ERROR}),
    SessionState.AI_THINKING: frozenset({SessionState.AI_SPEAKING, SessionState.ERROR, SessionState.IDLE}),
    SessionState.AI_SPEAKING: frozenset({SessionState.USER_SPEAKING, SessionState.IDLE, SessionState.ERROR}),
    SessionState.ERROR: frozenset({SessionState.IDLE, SessionState.ERROR}),
}

Hook = Callable[[str], Awaitable[None] | None]


class TransitionError(RuntimeError):
    pass


class SessionFSM:
    def __init__(self, session_id: str = "") -> None:
        self.session_id = session_id
        self._state: SessionState = SessionState.IDLE
        self._hooks: dict[str, list[Hook]] = {
            "on_enter_" + s.value: [] for s in SessionState
        }
        self._hooks.update({"on_exit_" + s.value: [] for s in SessionState})
        self._hooks["on_error"] = []
        self._barge_in: BargeInBus | None = None

    @property
    def state(self) -> SessionState:
        return self._state

    def register_hook(self, name: str, fn: Hook) -> None:
        if name not in self._hooks:
            logger.warning("fsm[%s]: 未知钩子 %s, 忽略", self.session_id, name)
            return
        self._hooks[name].append(fn)

    def bind_barge_in(self, bus: BargeInBus | None) -> None:
        self._barge_in = bus

    async def transition(self, new: SessionState, *, reason: str = "") -> None:
        if new not in _ALLOWED.get(self._state, frozenset()):
            raise TransitionError(
                f"fsm[{self.session_id}]: 非法转换 {self._state.value} -> {new.value} ({reason})"
            )
        old = self._state
        logger.info("fsm[%s]: %s -> %s reason=%s", self.session_id, old.value, new.value, reason)
        await self._fire("on_exit_" + old.value, reason)
        self._state = new
        if new is SessionState.ERROR:
            await self._fire("on_error", reason)
            if self._barge_in is not None:
                await self._barge_in.fire(f"fsm_error:{reason}")
        await self._fire("on_enter_" + new.value, reason)

    async def _fire(self, name: str, reason: str) -> None:
        for fn in list(self._hooks.get(name, [])):
            try:
                res = fn(reason)
                if res is not None:
                    await res
            except Exception as exc:
                logger.error("fsm[%s]: 钩子 %s 异常: %s", self.session_id, name, exc)

    def can_go(self, new: SessionState) -> bool:
        return new in _ALLOWED.get(self._state, frozenset())
