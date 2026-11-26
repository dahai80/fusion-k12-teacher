"""pytest global fixtures + live-LLM test gating."""

from __future__ import annotations

import os

import pytest

# P2: CI (ubuntu-latest, no fusion-mlx) fails/degrades when hitting a real LLM directly.
# live tests skip by default unless FUSION_K12_LIVE_TESTS=1; enable explicitly when the
# machine must load real models.
_LIVE_ENABLED = os.environ.get("FUSION_K12_LIVE_TESTS", "") == "1"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "live: tests that require fusion-mlx real model loading")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    # P2: when live is not explicitly enabled, skip tests marked live; guards against mislabeled/missed markers.
    skip_live = pytest.mark.skip(reason="requires fusion-mlx running (set FUSION_K12_LIVE_TESTS=1 to enable)")
    for item in items:
        if "live" in item.keywords and not _LIVE_ENABLED:
            item.add_marker(skip_live)


@pytest.fixture(autouse=True)
def _offline_llm(monkeypatch):
    """Non-live tests always point at an unreachable LLM address, aligning with CI (no fusion-mlx) behavior.

    On dev machines fusion-mlx runs persistently and requires an API key; unmocked engine
    tests would get 401 NonDegradableError instead of the expected graceful degradation —
    forcing base_url removes the environment difference.
    live tests (FUSION_K12_LIVE_TESTS=1) are unaffected and must be really reachable.
    """
    if not _LIVE_ENABLED:
        monkeypatch.setenv("FUSION_MLX_URL", "http://127.0.0.1:9/v1")
        monkeypatch.delenv("FUSION_MLX_API_KEY", raising=False)
        # issue #18: MLXClient.__init__ now reads the FUSION_MLX_MODEL env —
        # clear it in offline mode to keep shell env vars from polluting the test_default_model assertion
        monkeypatch.delenv("FUSION_MLX_MODEL", raising=False)
        # issue #34: client key is now resolved via fusion_core.config — clear the canonical
        # name and profile to keep shell env from polluting _auth_headers / prod RuntimeError assertions
        monkeypatch.delenv("FUSION_CLIENT_KEY", raising=False)
        monkeypatch.delenv("FUSION_PROFILE", raising=False)
    yield


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Clear rate-limit counters before each test, avoiding cross-test accumulation triggering 429."""
    try:
        from fusion_k12_teacher.serve import _rate_limiter
        _rate_limiter._hits.clear()
    except Exception:
        pass
    yield


@pytest.fixture(autouse=True)
def _isolate_scheduler_pidfile(monkeypatch):
    """TaskScheduler tests must not depend on the global pidfile lock — a same-machine serve holding
    the lock would make is_running=False.

    Mock _acquire_pidfile to return True directly, bypassing the fcntl cross-process lock
    (single-process tests need no dedup).
    Note: agent/__init__.py rebinds the scheduler name to an instance; import the TaskScheduler
    class from the submodule directly.
    """
    from fusion_k12_teacher.agent.scheduler import TaskScheduler
    monkeypatch.setattr(TaskScheduler, "_acquire_pidfile", lambda self: True)
    yield
