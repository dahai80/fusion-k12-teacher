"""审计模块 — v2.0 M3-T13/T14/T15。

可观测性: 每请求审计事件 (trace_id/route/status/duration/student_hash),
持久化至 Repository.audit_events 表, 定时归档清理, 管理员导出。
"""

from __future__ import annotations

from .event import AuditEvent, hash_pii, new_trace_id
from .logger import AuditLogger, get_audit_logger

__all__ = ["AuditEvent", "AuditLogger", "get_audit_logger", "hash_pii", "new_trace_id"]
