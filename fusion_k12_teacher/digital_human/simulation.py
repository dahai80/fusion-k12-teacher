"""IdleMotion — 纯 CPU 微动作 (眨眼/凝视/呼吸/barge-in 3 阶段)。

无 MLX 依赖。供 StaticAvatar/MuseTalkAvatar 生成 idle 帧。移植 linguakids simulation 思路。
"""

from __future__ import annotations

import logging
import math
import random
import time

logger = logging.getLogger(__name__)


class IdleMotion:
    def __init__(self, session_id: str = "") -> None:
        self.session_id = session_id
        self._t0 = time.monotonic()
        self._next_blink = self._sched_blink()

    @staticmethod
    def _sched_blink() -> float:
        return random.uniform(12.0, 20.0) / 60.0

    def now(self) -> float:
        return time.monotonic() - self._t0

    def breath(self, t: float | None = None) -> float:
        t = self.now() if t is None else t
        freq = 0.3
        return 0.5 + 0.5 * math.sin(2 * math.pi * freq * t)

    def gaze(self, t: float | None = None) -> tuple[float, float]:
        t = self.now() if t is None else t
        dx = 0.1 * math.sin(0.13 * t)
        dy = 0.08 * math.cos(0.17 * t)
        return dx, dy

    def blink(self, t: float | None = None) -> bool:
        t = self.now() if t is None else t
        if t >= self._next_blink:
            self._next_blink = t + self._sched_blink()
            return True
        return False

    def barge_in_progress(self, elapsed_ms: float) -> float:
        if elapsed_ms < 0:
            return 0.0
        if elapsed_ms >= 150:
            return 1.0
        x = elapsed_ms / 150.0
        return 1.0 / (1.0 + math.exp(-10 * (x - 0.5)))

    def barge_in_stages(self, elapsed_ms: float) -> tuple[float, float, float]:
        # 3 阶段 Sigmoid: 嘴形收敛 (0-40ms) → 眼神切换 (40-90ms) → 头部转向 (90-150ms)。
        # 每阶段各自 Sigmoid, 错峰 50ms, 模拟自然打断过渡 (linguakids 3-stage cascade)。
        def _sigmoid(t: float, start_ms: float, span_ms: float) -> float:
            if t < start_ms:
                return 0.0
            if t >= start_ms + span_ms:
                return 1.0
            x = (t - start_ms) / span_ms
            return 1.0 / (1.0 + math.exp(-10 * (x - 0.5)))
        lips = _sigmoid(elapsed_ms, 0.0, 40.0)
        eyes = _sigmoid(elapsed_ms, 40.0, 50.0)
        head = _sigmoid(elapsed_ms, 90.0, 60.0)
        return lips, eyes, head
