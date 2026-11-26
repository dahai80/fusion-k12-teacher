"""Audit module — v2.0 M3-T13/T14/T15.

Observability: per-request audit events (trace_id/route/status/duration/
student_hash), persisted to the Repository.audit_events table, scheduled
archive/purge, admin export.
"""

from __future__ import annotations

from .event import AuditEvent, hash_pii, new_trace_id
from .logger import AuditLogger, get_audit_logger

__all__ = ["AuditEvent", "AuditLogger", "get_audit_logger", "hash_pii", "new_trace_id"]
