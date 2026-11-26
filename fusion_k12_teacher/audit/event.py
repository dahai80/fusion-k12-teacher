"""Audit event model — M3-T13.

One audit event per request, including trace_id (trace passthrough), route,
status, duration, and the hashed student identifier (no raw PII stored).
Used for persistence + export + alerting baseline.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any


def new_trace_id() -> str:
    """Generate a trace_id — short hex string, passed through logs/audit/LLM."""
    return uuid.uuid4().hex


def hash_pii(value: Any) -> str:
    """Short PII hash — logs/audit never store the raw value. Empty input returns empty string."""
    s = str(value or "")
    if not s:
        return ""
    return "p" + hashlib.sha1(s.encode("utf-8")).hexdigest()[:10]


@dataclass
class AuditEvent:
    """Audit event — one audit record of a request/operation."""

    ts: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))
    trace_id: str = ""
    route: str = ""
    method: str = ""
    status: int = 0
    duration_ms: float = 0.0
    student_hash: str = ""
    llm_model: str = ""
    llm_status: str = ""
    client_ip: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AuditEvent:
        return cls(
            ts=str(d.get("ts", "")),
            trace_id=str(d.get("trace_id", "")),
            route=str(d.get("route", "")),
            method=str(d.get("method", "")),
            status=int(d.get("status", 0)),
            duration_ms=float(d.get("duration_ms", 0.0)),
            student_hash=str(d.get("student_hash", "")),
            llm_model=str(d.get("llm_model", "")),
            llm_status=str(d.get("llm_status", "")),
            client_ip=str(d.get("client_ip", "")),
            error=str(d.get("error", "")),
        )
