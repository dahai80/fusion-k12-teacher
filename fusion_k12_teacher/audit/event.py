"""审计事件模型 — M3-T13。

每请求一条审计事件, 含 trace_id (链路追踪透传)、路由、状态、耗时、
学生标识哈希 (不落原文 PII)。供持久化 + 导出 + 告警基线。
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any


def new_trace_id() -> str:
    """生成 trace_id — 16 进制短串, 供日志/审计/LLM 透传。"""
    return uuid.uuid4().hex


def hash_pii(value: Any) -> str:
    """PII 短哈希 — 日志/审计不落原文。空值返空串。"""
    s = str(value or "")
    if not s:
        return ""
    return "p" + hashlib.sha1(s.encode("utf-8")).hexdigest()[:10]


@dataclass
class AuditEvent:
    """审计事件 — 一条请求/操作的审计记录。"""

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
