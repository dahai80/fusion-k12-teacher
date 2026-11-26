"""A12: engine exception classification layer — separates degradable from non-degradable
failures; the latter must be rethrown.

The engine's original blanket `except Exception` uniformly degraded to default dataclasses,
swallowing config/auth errors (LLM-side 401/403) as "normal empty results", so operators
could not distinguish an LLM crash from normal empty output.

Classification:
- DegradableError: parse failure / empty LLM return / transient network jitter / 5xx server-side
  transient hard error — engine degrades to default dataclass and writes .error.
- NonDegradableError: config error / auth error (LLM 401/403) / model not configured — unrecoverable,
  must be rethrown so upper layers (CLI ClickException / serve 502) handle it explicitly.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class EngineError(Exception):
    """A12: engine exception base class — common root of all engine LLM-call errors."""


class DegradableError(EngineError):
    """Degradable error — parse failure / empty LLM return / transient network / 5xx server transient.
    Engine degrades to default dataclass."""


class NonDegradableError(EngineError):
    """Non-degradable error — config error / auth error (LLM 401/403) / model not configured.
    Must be rethrown, never silently degraded."""


def classify_http_status(status_code: int) -> bool:
    """A12: determine whether an HTTP status code is non-degradable.

    Only auth errors (401/403) are non-degradable — they are configuration problems the engine
    cannot recover from on its own; rethrow to expose them so operators can check the key. 5xx
    are LLM server-side transient hard errors (gateway jitter / model not ready); the engine
    keeps its existing graceful degradation (default dataclass + .error) and does not rethrow
    (otherwise it would break the established fault-tolerance contract of CLI/serve). 404
    (model not loaded) is handled separately in ai_client via _ModelNotFound re-select and
    does not go through this classification.
    """
    if status_code in (401, 403):
        logger.error("LLM auth failure (HTTP %d) — non-degradable, must rethrow", status_code)
        return True
    if 500 <= status_code < 600:
        logger.warning("LLM server-side transient hard error (HTTP %d) — degradable, engine returns default dataclass + .error", status_code)
        return False
    return False


def rethrow_if_fatal(exc: BaseException) -> None:
    """A11/A12: shared gatekeeper for the engine call layer — call inside the engine's
    `except Exception` block.

    Non-degradable errors (NonDegradableError: config/auth errors, i.e. LLM 401/403) must be
    rethrown and exposed, not degraded into a default dataclass by the blanket except.
    Degradable errors (parse failure / empty LLM return / 5xx transient) return None as-is and
    the engine continues degrading to the default dataclass + .error.

    Usage (first line of each engine method's catch block):
        except Exception as e:
            logger.error(...)
            rethrow_if_fatal(e)        # auth/config hard errors rethrow, otherwise continue degrading
            return LessonPlan(..., error=str(e))
    """
    if isinstance(exc, NonDegradableError):
        logger.error("Non-degradable error, aborting degradation and rethrowing: %s", exc)
        raise exc

