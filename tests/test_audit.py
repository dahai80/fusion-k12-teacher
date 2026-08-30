"""M3 审计 + 指标测试 — T13/T14/T15/T16。"""

from __future__ import annotations

import pytest

from fusion_k12_teacher.audit import (
    AuditEvent,
    AuditLogger,
    hash_pii,
    new_trace_id,
)
from fusion_k12_teacher.metrics import MetricsRegistry, get_metrics, render_prometheus
from fusion_k12_teacher.repository.sqlite_repo import SQLiteRepository

# ── T13: 审计事件模型 ──

class TestAuditEvent:
    def test_new_trace_id_unique(self):
        a = new_trace_id()
        b = new_trace_id()
        assert a != b
        assert len(a) == 32

    def test_hash_pii_stable(self):
        assert hash_pii("张三") == hash_pii("张三")
        assert hash_pii("张三") != hash_pii("李四")
        assert hash_pii("") == ""
        assert hash_pii(None) == ""

    def test_audit_event_roundtrip(self):
        e = AuditEvent(
            trace_id="abc", route="/api/x", method="POST", status=200,
            duration_ms=12.5, student_hash="phash",
        )
        d = e.to_dict()
        assert d["route"] == "/api/x"
        e2 = AuditEvent.from_dict(d)
        assert e2.route == "/api/x"
        assert e2.status == 200


# ── T14: 审计持久化 ──

class TestAuditPersistence:
    @pytest.fixture
    def repo(self, tmp_path):
        r = SQLiteRepository(str(tmp_path / "audit.db"))
        yield r
        r.close()

    @pytest.mark.asyncio
    async def test_logger_flush_to_repo(self, repo):
        al = AuditLogger(repo=repo, cap=100)
        al._flush_batch = 2
        await al.record(AuditEvent(route="/api/a", status=200))
        await al.record(AuditEvent(route="/api/b", status=500))
        await al.flush()
        rows = repo.load_audit(limit=10)
        assert len(rows) == 2
        assert {r["route"] for r in rows} == {"/api/a", "/api/b"}

    @pytest.mark.asyncio
    async def test_logger_no_repo_memory_only(self):
        al = AuditLogger(repo=None, cap=10)
        await al.record(AuditEvent(route="/api/x", status=200))
        await al.flush()  # 无 repo 不崩, 返 0
        assert len(al.recent(10)) == 1

    @pytest.mark.asyncio
    async def test_logger_aclose_flushes(self, repo):
        al = AuditLogger(repo=repo, cap=100)
        al._flush_batch = 50
        await al.record(AuditEvent(route="/api/c", status=200))
        await al.aclose()
        assert len(repo.load_audit(limit=10)) == 1

    def test_repo_purge_audit(self, repo):
        repo.save_audit([AuditEvent(route="/api/old", ts="2026-01-01T00:00:00").to_dict()])
        n = repo.purge_audit("2026-06-01T00:00:00")
        assert n == 1
        assert repo.load_audit(limit=10) == []

    def test_repo_load_audit_since(self, repo):
        repo.save_audit([
            AuditEvent(route="/api/1", ts="2026-01-01T00:00:00").to_dict(),
            AuditEvent(route="/api/2", ts="2026-06-01T00:00:00").to_dict(),
        ])
        rows = repo.load_audit(since_ts="2026-03-01T00:00:00", limit=10)
        assert len(rows) == 1
        assert rows[0]["route"] == "/api/2"

    def test_base_repo_default_audit_noop(self):
        from fusion_k12_teacher.repository.base import Repository
        class _Stub(Repository):
            def save_history(self, r): pass
            def load_history(self): return []
            def save_name_map(self, n, r): pass
            def load_name_map(self): return {}, {}
        s = _Stub()
        s.save_audit([{}])  # noop
        assert s.load_audit() == []
        assert s.purge_audit("x") == 0


# ── T16: 指标 ──

class TestMetrics:
    def test_record_request(self):
        m = MetricsRegistry()
        m.record_request("/api/x", 200, 0.1)
        m.record_request("/api/x", 200, 0.2)
        out = m.render()
        assert 'k12_request_total{route="/api/x",status="200"} 2.0' in out
        assert "k12_request_duration_seconds_count" in out

    def test_record_llm(self):
        m = MetricsRegistry()
        m.record_llm("qwen", True, 1.5)
        m.record_llm("qwen", False, 0.5)
        out = m.render()
        assert 'k12_llm_call_total{model="qwen",status="ok"} 1.0' in out
        assert 'k12_llm_call_total{model="qwen",status="error"} 1.0' in out

    def test_gauges(self):
        m = MetricsRegistry()
        m.set_active_jobs(3)
        m.set_db_pool_inuse(5)
        out = m.render()
        assert "k12_active_jobs 3.0" in out
        assert "k12_db_pool_inuse 5.0" in out

    def test_histogram_buckets_cumulative(self):
        m = MetricsRegistry()
        m.record_request("/api/h", 200, 0.01)   # <=0.01
        m.record_request("/api/h", 200, 0.3)    # <=0.5
        out = m.render()
        # le=0.01 应有 1, le=0.5 应有 2 (累计)
        assert 'le="0.01"} 1.0' in out
        assert 'le="0.5"} 2.0' in out

    def test_render_prometheus_singleton(self):
        out1 = render_prometheus()
        out2 = render_prometheus()
        assert "# TYPE k12_request_total counter" in out1
        assert out1 == out2  # 同一注册表, 内容一致
        # 单例: 两次 render 同一对象
        assert get_metrics() is get_metrics()
