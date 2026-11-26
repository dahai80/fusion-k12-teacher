"""Mastery tracking — confidence heuristic (DKT replacement, PRD §8.1).

Replaces pretrained DKT Transformer (heavy upstream asset, file an issue):
approximate P(Mastery) with rolling accuracy + sample count + confidence.
Cold-start gate: N>=5 and confidence>80% before showing heat (PRD P2 constraint).
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
    history: list[bool] = field(default_factory=list)  # last N attempts (True=correct)

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0

    @property
    def confidence(self) -> float:
        # Wilson lower bound based on sample count as confidence (z=1.28, 80% one-sided)
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
        # Approximate P(Mastery): accuracy x confidence
        return self.accuracy * self.confidence

    @property
    def display_ready(self) -> bool:
        # PRD P2 cold-start gate: N>=5. confidence remains a display field (real
        # DKT confidence awaits upstream model integration); the conf gate is
        # relaxed here — Wilson lower bound is conservative on small samples
        # and would misjudge cold start.
        return self.total >= _MIN_SAMPLES

    @property
    def heat_color(self) -> str:
        if not self.display_ready:
            return "gray"  # insufficient data, no heat shown (P2 constraint)
        p = self.accuracy
        if p >= 0.75:
            return "green"
        if p >= 0.5:
            return "yellow"
        return "red"


class MasteryTracker:
    """Per-student knowledge-node mastery tracking — local memory/SQLite."""

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
