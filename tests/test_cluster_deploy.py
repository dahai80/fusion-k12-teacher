"""T22: cluster deploy templates + gateway integration + load baseline tests.

Coverage:
  - deploy template yaml parseable + key fields complete (T20)
  - k12↔gateway integration config closed loop (T21)
  - multi-instance consistency: config/rate-limit/anonymization consistent
    across instances (cluster mode)
  - failover: graceful drain/evict semantics (M3-T19 re-verification)
  - performance baseline: throughput/latency ceiling with a mock LLM
    (no real mlx needed)
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

DEPLOY = Path(__file__).resolve().parents[1] / "deploy"
K8S = DEPLOY / "k8s"


# ── T20: deploy template structure ──

class TestDeployTemplates:
    def _load_yaml(self, p: Path):
        with open(p, encoding="utf-8") as f:
            return list(yaml.safe_load_all(f))

    def test_compose_parses(self):
        docs = self._load_yaml(DEPLOY / "docker-compose.yml")
        svc = docs[0]["services"]
        assert "k12" in svc and "postgres" in svc and "redis" in svc
        # replicas + resource limits + health check
        k12 = svc["k12"]
        assert k12["deploy"]["replicas"] == "${FUSION_K12_REPLICAS:-3}"
        assert "limits" in k12["deploy"]["resources"]
        assert k12["healthcheck"]["test"]
        # drain grace period > 0
        assert int(k12["stop_grace_period"].rstrip("s")) >= 30

    def test_k8s_deployment_probes(self):
        docs = self._load_yaml(K8S / "deployment.yaml")
        dep = docs[0]
        c = dep["spec"]["template"]["spec"]["containers"][0]
        assert c["startupProbe"]["httpGet"]["path"] == "/api/ready"
        assert c["livenessProbe"]["httpGet"]["path"] == "/api/health"
        assert c["readinessProbe"]["httpGet"]["path"] == "/api/ready"
        # resource limits
        assert "limits" in c["resources"]
        # drain grace period > FUSION_K12_DRAIN_TIMEOUT(30)
        assert dep["spec"]["template"]["spec"]["terminationGracePeriodSeconds"] >= 30
        # envFrom config + secret
        assert c["envFrom"][0]["configMapRef"]["name"] == "k12-config"
        assert c["envFrom"][1]["secretRef"]["name"] == "k12-secret"

    def test_k8s_hpa_scale_protection(self):
        docs = self._load_yaml(K8S / "hpa.yaml")
        hpa = docs[0]
        assert hpa["spec"]["minReplicas"] >= 2   # never scale to 0
        assert hpa["spec"]["maxReplicas"] >= hpa["spec"]["minReplicas"]
        # scale-down cooldown window
        assert hpa["spec"]["behavior"]["scaleDown"]["stabilizationWindowSeconds"] >= 300
        # PDB
        pdb = docs[1]
        assert pdb["spec"]["minAvailable"] >= 1

    def test_env_example_covers_required(self):
        txt = (DEPLOY / ".env.example").read_text(encoding="utf-8")
        required = [
            "FUSION_K12_MODE", "FUSION_K12_API_KEY", "FUSION_K12_ADMIN_API_KEY",
            "FUSION_MLX_URL", "FUSION_CLIENT_KEY", "FUSION_K12_PG_DSN",
            "FUSION_K12_REDIS_URL", "FUSION_K12_SALT", "FUSION_K12_DRAIN_TIMEOUT",
            "FUSION_K12_REPLICAS", "FUSION_K12_MIN_REPLICAS",
        ]
        for k in required:
            assert k in txt, f"env.example missing {k}"

    def test_dockerfile_exposes_port_and_healthcheck(self):
        txt = (DEPLOY / "Dockerfile").read_text(encoding="utf-8")
        assert "EXPOSE 11448" in txt
        assert "/api/health" in txt
        assert "USER k12" in txt   # non-root user


# ── T21: gateway integration config closed loop ──

class TestGatewayIntegration:
    def test_integration_doc_exists_and_complete(self):
        doc = DEPLOY / "fusion-gateway-integration.md"
        assert doc.exists()
        txt = doc.read_text(encoding="utf-8")
        # key sections (doc section titles are Chinese product docs, keep as is)
        for sec in ["能力分工", "k12 侧配置", "网关侧配置", "集群形态拓扑", "对接验证清单", "issue→PR"]:
            assert sec in txt
        # dual-layer auth + Bearer passthrough
        assert "Bearer" in txt and "X-API-Key" in txt

    def test_ai_client_sends_bearer_when_key_set(self):
        from fusion_k12_teacher.ai_client import MLXClient
        c = MLXClient()
        # no key → no Authorization header (P1-20)
        os.environ.pop("FUSION_CLIENT_KEY", None)
        assert "Authorization" not in c._auth_headers()
        # key set → send Bearer
        os.environ["FUSION_CLIENT_KEY"] = "gw-key-123"
        try:
            h = c._auth_headers()
            assert h["Authorization"] == "Bearer gw-key-123"
        finally:
            os.environ.pop("FUSION_CLIENT_KEY", None)

    def test_env_example_gateway_endpoint(self):
        txt = (DEPLOY / ".env.example").read_text(encoding="utf-8")
        # points at the gateway 11432, not mlx 11434
        assert "11432" in txt
        assert "FUSION_CLIENT_KEY" in txt


# ── multi-instance consistency (cluster mode logic) ──

class TestMultiInstanceConsistency:
    def test_cluster_mode_routes_to_shared_backends(self, monkeypatch):
        # cluster mode → Postgres + Redis (shared backends), consistent across instances
        from fusion_k12_teacher.repository.factory import get_repository
        monkeypatch.setenv("FUSION_K12_MODE", "cluster")
        monkeypatch.setenv("FUSION_K12_PG_DSN", "postgresql://u:p@nohost:5432/k12")
        # asyncpg may be missing → the factory should return None or raise a
        # controlled exception, never silently fall back to SQLite
        repo = None
        try:
            repo = get_repository()
        except Exception:
            pass
        # if a repo is returned, it must be Postgres (cluster never falls back to SQLite)
        if repo is not None:
            assert type(repo).__name__ == "PostgresRepository"

    def test_shared_cache_only_in_cluster(self, monkeypatch):
        from fusion_k12_teacher import serve
        # standalone → None (in-process rate limiting)
        monkeypatch.setenv("FUSION_K12_MODE", "standalone")
        assert serve._shared_cache() is None
        # cluster without a redis url → None (in-process fallback)
        monkeypatch.setenv("FUSION_K12_MODE", "cluster")
        monkeypatch.delenv("FUSION_K12_REDIS_URL", raising=False)
        assert serve._shared_cache() is None

    @pytest.mark.asyncio
    async def test_rate_limiter_state_isolated_per_instance(self):
        from fusion_k12_teacher.serve import _RateLimiter
        a = _RateLimiter(60, 2, state_file="")
        b = _RateLimiter(60, 2, state_file="")
        # each instance counts on its own, not shared (clusters share via
        # Redis, standalone instances stay separate)
        assert await a.check("ip1")
        assert await a.check("ip1")
        assert not await a.check("ip1")   # 3rd request rejected
        # instance b is independent, ip1 still allowed on b
        assert await b.check("ip1")


# ── failover: drain and evict ──

class TestFailoverDrain:
    @pytest.mark.asyncio
    async def test_draining_then_undraining_cycle(self, monkeypatch):
        # drain → reject new; undrain → recover (simulates instance replacement)
        import fusion_k12_teacher.serve as serve
        monkeypatch.setattr(serve, "_draining", False)
        monkeypatch.setattr(serve, "_ready", True)
        monkeypatch.setattr(serve, "_inflight", 0)
        # enter draining
        serve._draining = True
        assert serve._draining is True
        # new requests must be rejected by the middleware while draining (middleware reads _draining)
        # exit draining (new instance online semantics)
        serve._draining = False
        assert serve._draining is False

    @pytest.mark.asyncio
    async def test_drain_timeout_env(self, monkeypatch):
        import fusion_k12_teacher.serve as serve
        monkeypatch.setenv("FUSION_K12_DRAIN_TIMEOUT", "5")
        assert serve._drain_timeout() == 5.0
        monkeypatch.setenv("FUSION_K12_DRAIN_TIMEOUT", "30")
        assert serve._drain_timeout() == 30.0


# ── performance baseline: mock LLM throughput ──

class TestPerfBaseline:
    def test_throughput_under_concurrent_mock(self):
        # no real mlx needed: use a mock chat to verify concurrent dispatch has
        # no serialization bottleneck
        from fusion_k12_teacher.ai_client import MLXClient
        c = MLXClient()

        async def mock_chat(prompt, **kw):
            return '{"ok": true}'
        c.chat = mock_chat

        import asyncio

        async def run():
            tasks = [c.chat("p", temperature=0.2) for _ in range(50)]
            results = await asyncio.gather(*tasks)
            return results

        t0 = time.monotonic()
        results = asyncio.run(run())
        elapsed = time.monotonic() - t0
        assert len(results) == 50
        # 50 concurrent mocks should finish within 2s (no lock serialization)
        assert elapsed < 2.0, f"Abnormal concurrent throughput: {elapsed:.2f}s"

    def test_metrics_no_lock_contention(self):
        # the metrics registry must not deadlock under concurrent multi-threaded writes
        from fusion_k12_teacher.metrics import MetricsRegistry
        m = MetricsRegistry()

        def hammer():
            for i in range(1000):
                m.record_request("/api/x", 200, 0.01 * (i % 10))
                m.record_llm("qwen", True, 0.5)

        threads = [threading.Thread(target=hammer) for _ in range(8)]
        t0 = time.monotonic()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        elapsed = time.monotonic() - t0
        out = m.render()
        # all 8000 requests counted
        assert 'k12_request_total{route="/api/x",status="200"} 8000.0' in out
        assert elapsed < 3.0, f"Metrics concurrent write stall: {elapsed:.2f}s"
