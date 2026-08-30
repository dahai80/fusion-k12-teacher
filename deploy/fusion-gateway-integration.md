# T21: fusion-gateway 对接指南

本工程 (fusion-k12-teacher) 通过 fusion-gateway 路由所有 LLM 流量。网关属上游项目 (Go, 独立仓库), **本工程不修改其代码** — 仅对接配置, 上游不足走 issue→PR 流程。

## 1. 能力分工

| 能力 | 责任方 | 实现位置 |
|------|--------|---------|
| 负载均衡 (轮询/最少连接) | 网关 (上游) | gateway `server` + 节点健康检查 |
| API Key 鉴权 | 网关 (上游) | gateway `auth.enabled` + `auth.master_key` |
| 限流 (RPM/TPM, per-key) | 网关 (上游) | gateway `route.rate_limit` |
| 路由 (local/hybrid/cloud) | 网关 (上游) | gateway `route.mode` |
| 响应缓存 | 网关 (上游) | gateway `cache` |
| 熔断 | 网关 (上游) | gateway `route.circuit_breaker` |
| k12 自身 API Key 鉴权 | 本工程 | `FUSION_K12_API_KEY` (面向调用方) |
| k12 自身限流 (进程内/Redis) | 本工程 | `_RateLimiter` (面向调用方) |
| 审计/指标/排水/探针 | 本工程 | M3 已实现 |

**双层鉴权**: 调用方 → (X-API-Key) → k12 实例 → (Bearer gateway-key) → fusion-gateway → fusion-mlx。两层 key 独立, 各自轮换。

## 2. k12 侧配置 (env)

```bash
# 指向网关 (非直连 fusion-mlx 11434)
FUSION_MLX_URL=http://fusion-gateway:11432/v1
# 网关授权 key (k12 透传 Authorization: Bearer <key>, 见 ai_client.py:143-146)
FUSION_MLX_API_KEY=<gateway-auth-key>
# 默认模型 (网关按 route 配置分发)
FUSION_MLX_MODEL=Qwen3.5-9B-4bit
```

k12 代码已就绪 (M1 起): `ai_client.py` `_auth_headers()` 无 key 不发 Bearer (P1-20 修复), 避免对需认证网关必 401。

## 3. 网关侧配置 (config.yaml — 上游项目, 仅示例, 不在本仓库)

网关配置文件属 fusion-gateway 仓库, 此处给出 k12 对接所需的配置片段供运维参考。完整字段见上游 `config.example.yaml`。

```yaml
server:
  port: 11432
  auto_start:
    enabled: true
    command: ~/claude-home/fusion-mlx/start.sh start
    stop_cmd: ~/claude-home/fusion-mlx/start.sh stop
    wait_url: http://127.0.0.1:11434/health
    wait_secs: 120

auth:
  enabled: true
  master_key: "<运维主密钥>"   # 旁路限流/模型白名单

route:
  mode: hybrid
  rate_limit:
    enabled: true
    # per-key RPM/TPM — k12 客户端 key 的限流在此配
  circuit_breaker:
    failure_threshold: 5
  retry:
    max_retries: 2

cache:
  enabled: true
  backend: redis
  redis:
    addr: redis:6379
```

## 4. 集群形态拓扑

```
调用方 ──X-API-Key──▶ k12 实例×N (FUSION_K12_REPLICAS)
                        │  (k12 自身鉴权/限流/审计/指标)
                        ▼  Bearer gateway-key
                  fusion-gateway:11432 (负载/鉴权/限流/路由/熔断/缓存)
                        │
                        ▼
                  fusion-mlx 节点×M (port 11434, 上游扩缩容)
```

- k12 多实例经 Service 暴露给网关, 网关轮询健康实例
- 网关到 mlx 的扩缩容属上游 (见 §4.6), 走 issue→PR

## 5. 对接验证清单

- [ ] `FUSION_MLX_URL` 指向网关, 非 11434
- [ ] `FUSION_MLX_API_KEY` 与网关 `auth` 配置的 key 一致
- [ ] 网关健康: `curl http://fusion-gateway:11432/healthz` 200
- [ ] k12 探针: `/api/health` (liveness) `/api/ready` (readiness, 含 mlx 探测)
- [ ] k12 `/api/metrics` 可观测 `k12_llm_call_total{status="error"}` — 网关故障会反映在此
- [ ] 排水验证: `kill -TERM <pid>` → 新请求 503, 在途完成后退出 (M3-T19)

## 6. 上游不足 → issue→PR 流程

如对接中发现 fusion-gateway 缺失 k12 所需能力 (如: 无法透传 trace-id、不支持 k12 的健康检查语义、限流维度不足), 遵循流程:

1. 在 `fusion-gateway` 仓库提 issue (英文), 描述场景 + 复现 + 期望行为
2. 提 PR 实现修复, 跟随提交落地 code
3. 本工程侧以配置/适配层消化可绕过部分, 不阻塞 M4 发布

已知 (本工程对接侧已规避, 无需上游改动):
- trace-id: 网关注入, k12 中间件透传 (M3-T13 已用 `X-Trace-Id` header)
- 排水: k12 自管 (M3-T19), 不依赖网关摘流 (网关按 `/api/health` 健康检查自然剔除排水中实例)
