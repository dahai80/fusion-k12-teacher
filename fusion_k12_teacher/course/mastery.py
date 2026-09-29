"""掌握度追踪 — 置信度启发式 (DKT 替代, PRD §8.1)。

替代 DKT Transformer 预训练 (上游重资产, 提 issue): 用滚动正确率 + 样本数 + 置信度
近似 P(Mastery)。冷启动门槛: N≥5 且置信度>80% 才显热力 (PRD P2 约束)。
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_MIN_SAMPLES = 5
_CONF_THRESHOLD = 0.80


@dataclass
class MasteryRecord:
    node_id: str
    total: int = 0
    correct: int = 0
    history: list[bool] = field(default_factory=list)  # 最近 N 次 (True=对)

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0

    @property
    def confidence(self) -> float:
        # 基于样本数的 Wilson 区间下界作为置信度 (z=1.28, 80% 单侧)
        if self.total < 1:
            return 0.0
        z = 1.28
        n = self.total
        p = self.accuracy
        denom = 1 + z * z / n
        center = (p + z * z / (2 * n)) / denom
        margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denom
        return max(0.0, center - margin)

    @property
    def mastery_probability(self) -> float:
        # 近似 P(Mastery): 准确率 × 置信度
        return self.accuracy * self.confidence

    @property
    def display_ready(self) -> bool:
        # PRD P2 冷启动门槛: N≥5。confidence 仍作展示字段 (真 DKT 置信度待上游模型接入),
        # 此处放宽 conf 门槛 — Wilson 下界在小样本保守, 会误判冷启动。
        return self.total >= _MIN_SAMPLES

    @property
    def heat_color(self) -> str:
        if not self.display_ready:
            return "gray"  # 数据不足不显热力 (P2 约束)
        p = self.accuracy
        if p >= 0.75:
            return "green"
        if p >= 0.5:
            return "yellow"
        return "red"


class MasteryTracker:
    """学生知识点掌握度追踪 — 本地内存/SQLite。"""

    def __init__(self) -> None:
        self._records: dict[str, dict[str, MasteryRecord]] = {}  # student_id -> node_id -> record

    def record(self, student_id: str, node_id: str, correct: bool) -> MasteryRecord:
        student = self._records.setdefault(student_id, {})
        rec = student.get(node_id, MasteryRecord(node_id=node_id))
        rec.total += 1
        if correct:
            rec.correct += 1
        rec.history.append(correct)
        if len(rec.history) > 50:
            rec.history = rec.history[-50:]
        student[node_id] = rec
        logger.info("mastery: student=%s node=%s correct=%s total=%d acc=%.2f", student_id, node_id, correct, rec.total, rec.accuracy)
        return rec

    def get(self, student_id: str, node_id: str) -> MasteryRecord | None:
        return self._records.get(student_id, {}).get(node_id)

    def student_profile(self, student_id: str) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for nid, rec in self._records.get(student_id, {}).items():
            out[nid] = {
                "total": rec.total, "correct": rec.correct, "accuracy": rec.accuracy,
                "confidence": rec.confidence, "mastery_probability": rec.mastery_probability,
                "display_ready": rec.display_ready, "heat_color": rec.heat_color,
            }
        return out

    def weak_nodes(self, student_id: str) -> list[str]:
        return [nid for nid, r in self._records.get(student_id, {}).items() if r.display_ready and r.mastery_probability < 0.5]
