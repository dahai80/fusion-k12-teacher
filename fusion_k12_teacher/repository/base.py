"""Repository abstraction layer — v2.0 persistence decoupling.

The business layer programs against the Repository interface and is unaware
of the concrete backend (SQLite/Postgres).
standalone mode uses SQLiteRepository, cluster mode uses PostgresRepository
(M1-T2).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class Repository(ABC):
    """Persistence repository abstract base class.

    One set of read/write methods per entity (history/name_map/audit).
    Backend implementations own serialization/concurrency/transactions;
    callers only pass structured dicts.
    """

    @abstractmethod
    def save_history(self, records: list[dict[str, Any]]) -> None:
        """Overwrite-save task execution history (whole list)."""

    @abstractmethod
    def load_history(self) -> list[dict[str, Any]]:
        """Load all task execution history (ascending by time)."""

    @abstractmethod
    def save_name_map(self, name_map: dict[str, str], reverse_map: dict[str, str]) -> None:
        """Save the anonymization mapping (name→id forward + id→name reverse)."""

    @abstractmethod
    def load_name_map(self) -> tuple[dict[str, str], dict[str, str]]:
        """Load the anonymization mapping, returns (name_map, reverse_map)."""

    # ── M2-T11: task locks (cross-instance cron dedup) ──
    # In cluster mode multiple instances each arm cron; grabbing a DB row lock
    # prevents the same task from executing twice.
    # owner = instance identity (hostname+pid), ttl = lock timeout in seconds
    # (prevents a crashed lock holder from blocking forever).

    def try_lock(self, task_id: str, owner: str, ttl: float = 300.0) -> bool:
        """Try to acquire the task execution lock — True on success, False when
        already held (and not expired).

        Idempotent: re-acquiring with the same owner returns True
        (re-entry/renewal scenarios).
        Expired locks can be re-acquired after being reaped.
        Default implementation (standalone single process needs no DB lock)
        always returns True.
        """
        return True

    def renew_lock(self, task_id: str, owner: str, ttl: float = 300.0) -> bool:
        """Renew the task lock — only the lock owner may renew, True on success. No-op by default."""
        return True

    def release_lock(self, task_id: str, owner: str) -> None:
        """Release the task lock — only the lock owner may release. No-op by default."""

    def reap_expired_locks(self) -> int:
        """Clean up expired locks — returns the number cleaned. No-op by default, returns 0."""
        return 0

    # ── M3-T14: audit persistence ──
    # The audit_events table stores per-request audit records
    # (ts/trace_id/route/status/duration/student_hash/...).
    # Retention: purge_audit(days) cleans records older than N days; archiving
    # can be attached separately.

    def save_audit(self, records: list[dict[str, Any]]) -> None:
        """Batch-write audit events (append semantics, not overwrite). No-op by default."""

    def load_audit(
        self, since_ts: str = "", limit: int = 1000
    ) -> list[dict[str, Any]]:
        """Load audit events — ascending from since_ts, limited to limit rows. Returns empty by default."""
        return []

    def purge_audit(self, before_ts: str) -> int:
        """Purge audit events before before_ts — returns the number deleted. Default 0."""
        return 0

    # ── Teacher identity ──
    # teachers/sessions/materials tables: register/login/tokens/resource library.

    def create_teacher(self, teacher: dict[str, Any]) -> str:
        """Write a teacher record, returns teacher_id. No-op by default."""
        return ""

    def get_teacher_by_username(self, username: str) -> dict[str, Any] | None:
        """Look up a teacher by username. Default None."""
        return None

    def get_teacher(self, teacher_id: str) -> dict[str, Any] | None:
        """Look up a teacher by id. Default None."""
        return None

    def create_session(self, token: str, teacher_id: str, expires_at: float) -> None:
        """Write a login session (token->teacher_id, expiry time). No-op by default."""

    def get_session(self, token: str) -> dict[str, Any] | None:
        """Look up a session. Default None."""
        return None

    def delete_session(self, token: str) -> None:
        """Log out a session. No-op by default."""

    def save_material(self, material: dict[str, Any]) -> str:
        """Save a generated resource, returns the material id. No-op by default."""
        return ""

    def list_materials(
        self,
        teacher_id: str,
        *,
        type: str | None = None,
        subject: str | None = None,
        grade: str | None = None,
        lesson_id: str | None = None,
        edition: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List teacher resources (filtered by criteria). Default empty list."""
        return []

    def get_material(self, material_id: str) -> dict[str, Any] | None:
        """Fetch a single resource. Default None."""
        return None

    def delete_material(self, material_id: str, teacher_id: str) -> bool:
        """Delete a resource (teacher_id ownership must be verified). Default False."""
        return False

    # issue #17: unbounded resource growth on disk — purge by age + per-teacher
    # cap, executed lazily at serve startup.
    def purge_old_materials(
        self, before_ts: str = "", max_per_teacher: int = 500
    ) -> int:
        """Purge old resources — delete everything before before_ts, and delete
        older records beyond max_per_teacher per teacher.
        Returns the number deleted. No-op by default, returns 0."""
        return 0

    def close(self) -> None:
        """Release backend resources (connections/file handles). No-op by default."""

    def health(self) -> bool:
        """Backend health probe, used by /api/ready. Default True."""
        return True
