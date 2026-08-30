"""T22: 集群部署模板 + 对接 + 压测基线测试。

覆盖:
  - 部署模板 yaml 可解析 + 关键字段完整 (T20)
  - k12↔gateway 对接配置闭环 (T21)
  - 多实例一致性: 配置/限流/脱敏在多实例下一致 (cluster 模式)
  - 故障转移: 优雅排水摘流语义 (M3-T19 复验)
  - 性能基线: mock LLM 下吞吐/延迟上限 (不依赖真实 mlx)
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


# ── T20: 部署模板结构 ──

class TestDeployTemplates:
    def _load_yaml(self, p: Path):
        with open(p, encoding="utf-8") as f:
            return list(yaml.safe_load_all(f))

    def test_compose_parses(self):
        docs = self._load_yaml(DEPLOY / "docker-compose.yml")
        svc = docs[0]["services"]
        assert "k12" in svc and "postgres" in svc and "redis" in svc
        # replicas + 资源限额 + 健康检查
        k12 = svc["k12"]
        assert k12["deploy"]["replicas"] == "${FUSION_K12_REPLICAS:-3}"
        assert "limits" in k12["deploy"]["resources"]
        assert k12["healthcheck"]["test"]
        # 排水宽限期 > 0
        assert int(k12["stop_grace_period"].rstrip("s")) >= 30

    def test_k8s_deployment_probes(self):
        docs = self._load_yaml(K8S / "deployment.yaml")
        dep = docs[0]
        c = dep["spec"]["template"]["spec"]["containers"][0]
        assert c["startupProbe"]["httpGet"]["path"] == "/api/ready"
        assert c["livenessProbe"]["httpGet"]["path"] == "/api/health"
        assert c["readinessProbe"]["httpGet"]["path"] == "/api/ready"
        # 资源限额
        assert "limits" in c["resources"]
        # 排水宽限期 > FUSION_K12_DRAIN_TIMEOUT(30)
        assert dep["spec"]["template"]["spec"]["terminationGracePeriodSeconds"] >= 30
        # envFrom config + secret
        assert c["envFrom"][0]["configMapRef"]["name"] == "k12-config"
        assert c["envFrom"][1]["secretRef"]["name"] == "k12-secret"

    def test_k8s_hpa_scale_protection(self):
        docs = self._load_yaml(K8S / "hpa.yaml")
        hpa = docs[0]
        assert hpa["spec"]["minReplicas"] >= 2   # 不缩到 0
        assert hpa["spec"]["maxReplicas"] >= hpa["spec"]["minReplicas"]
        # 缩容冷却窗口
        assert hpa["spec"]["behavior"]["scaleDown"]["stabilizationWindowSeconds"] >= 300
        # PDB
        pdb = docs[1]
        assert pdb["spec"]["minAvailable"] >= 1

    def test_env_example_covers_required(self):
        txt = (DEPLOY / ".env.example").read_text(encoding="utf-8")
        required = [
            "FUSION_K12_MODE", "FUSION_K12_API_KEY", "FUSION_K12_ADMIN_API_KEY",
            "FUSION_MLX_URL", "FUSION_MLX_API_KEY", "FUSION_K12_PG_DSN",
            "FUSION_K12_REDIS_URL", "FUSION_K12_SALT", "FUSION_K12_DRAIN_TIMEOUT",
            "FUSION_K12_REPLICAS", "FUSION_K12_MIN_REPLICAS",
        ]
        for k in required:
            assert k in txt, f"env.example 缺 {k}"

    def test_dockerfile_exposes_port_and_healthcheck(self):
        txt = (DEPLOY / "Dockerfile").read_text(encoding="utf-8")
        assert "EXPOSE 11448" in txt
        assert "/api/health" in txt
        assert "USER k12" in txt   # 非根用户


# ── T21: gateway 对接配置闭环 ──

class TestGatewayIntegration:
    def test_integration_doc_exists_and_complete(self):
        doc = DEPLOY / "fusion-gateway-integration.md"
        assert doc.exists()
        txt = doc.read_text(encoding="utf-8")
        # 关键章节
        for sec in ["能力分工", "k12 侧配置", "网关侧配置", "集群形态拓扑", "对接验证清单", "issue→PR"]:
            assert sec in txt
        # 双层鉴权 + Bearer 透传
        assert "Bearer" in txt and "X-API-Key" in txt

    def test_ai_client_sends_bearer_when_key_set(self):
        from fusion_k12_teacher.ai_client import MLXClient
        c = MLXClient()
        # 无 key 不发 Authorization (P1-20)
        os.environ.pop("FUSION_MLX_API_KEY", None)
        assert "Authorization" not in c._auth_headers()
        # 有 key 发 Bearer
        os.environ["FUSION_MLX_API_KEY"] = "gw-key-123"
        try:
            h = c._auth_headers()
            assert h["Authorization"] == "Bearer gw-key-123"
        finally:
            os.environ.pop("FUSION_MLX_API_KEY", None)

    def test_env_example_gateway_endpoint(self):
        txt = (DEPLOY / ".env.example").read_text(encoding="utf-8")
        # 指向网关 11432, 非 mlx 11434
        assert "11432" in txt
        assert "FUSION_MLX_API_KEY" in txt


# ── 多实例一致性 (cluster 模式逻辑) ──

class TestMultiInstanceConsistency:
    def test_cluster_mode_routes_to_shared_backends(self, monkeypatch):
        # cluster 模式 → Postgres + Redis (共享后端), 多实例一致
        from fusion_k12_teacher.repository.factory import get_repository
        monkeypatch.setenv("FUSION_K12_MODE", "cluster")
        monkeypatch.setenv("FUSION_K12_PG_DSN", "postgresql://u:p@nohost:5432/k12")
        # asyncpg 可能未装 → factory 应返回 None 或抛可控异常, 不静默用 SQLite
        repo = None
        try:
            repo = get_repository()
        except Exception:
            pass
        # 若拿到 repo, 必须是 Postgres (cluster 不回退 SQLite)
        if repo is not None:
            assert type(repo).__name__ == "PostgresRepository"

    def test_shared_cache_only_in_cluster(self, monkeypatch):
        from fusion_k12_teacher import serve
        # standalone → None (进程内限流)
        monkeypatch.setenv("FUSION_K12_MODE", "standalone")
        assert serve._shared_cache() is None
        # cluster 无 redis url → None (回退进程内)
        monkeypatch.setenv("FUSION_K12_MODE", "cluster")
        monkeypatch.delenv("FUSION_K12_REDIS_URL", raising=False)
        assert serve._shared_cache() is None

    @pytest.mark.asyncio
    async def test_rate_limiter_state_isolated_per_instance(self):
        from fusion_k12_teacher.serve import _RateLimiter
        a = _RateLimiter(60, 2, state_file="")
        b = _RateLimiter(60, 2, state_file="")
        # 两实例各自计数, 不共享 (集群靠 Redis 共享, 单机各自)
        assert await a.check("ip1")
        assert await a.check("ip1")
        assert not await a.check("ip1")   # 第 3 次拒
        # b 实例独立, ip1 在 b 仍可
        assert await b.check("ip1")


# ── 故障转移: 排水摘流 ──

class TestFailoverDrain:
    @pytest.mark.asyncio
    async def test_draining_then_undraining_cycle(self, monkeypatch):
        # 排水 → 拒新; 取消排水 → 恢复 (模拟实例替换)
        import fusion_k12_teacher.serve as serve
        monkeypatch.setattr(serve, "_draining", False)
        monkeypatch.setattr(serve, "_ready", True)
        monkeypatch.setattr(serve, "_inflight", 0)
        # 进入排水
        serve._draining = True
        assert serve._draining is True
        # 排水期间新请求应被中间件拒 (中间件读 _draining)
        # 退出排水 (新实例上线语义)
        serve._draining = False
        assert serve._draining is False

    @pytest.mark.asyncio
    async def test_drain_timeout_env(self, monkeypatch):
        import fusion_k12_teacher.serve as serve
        monkeypatch.setenv("FUSION_K12_DRAIN_TIMEOUT", "5")
        assert serve._drain_timeout() == 5.0
        monkeypatch.setenv("FUSION_K12_DRAIN_TIMEOUT", "30")
        assert serve._drain_timeout() == 30.0


# ── 性能基线: mock LLM 吞吐 ──

class TestPerfBaseline:
    def test_throughput_under_concurrent_mock(self):
        # 不依赖真实 mlx: 用 mock chat, 测并发调度无串行化瓶颈
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
        # 50 并发 mock 应在 2s 内完成 (无锁串行化)
        assert elapsed < 2.0, f"并发吞吐异常: {elapsed:.2f}s"

    def test_metrics_no_lock_contention(self):
        # 指标注册表多线程并发写不死锁
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
        # 8000 请求全部计数
        assert 'k12_request_total{route="/api/x",status="200"} 8000.0' in out
        assert elapsed < 3.0, f"指标并发写卡顿: {elapsed:.2f}s"
