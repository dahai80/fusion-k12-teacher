---
doc_id: fusion-k12-teacher/troubleshooting
product: fusion-k12-teacher
class: app
entry: guided-ui
doc_type: troubleshooting
title: { zh: "Fusion-K12-Teacher 故障排查", en: "Fusion-K12-Teacher troubleshooting" }
audience: engineer
status: draft
version: 2.2.6
updated: 2026-11-07
owner: "@dahai"
source_of_truth:
  - start.sh
  - .env.example
  - fusion_k12_teacher/cli.py
  - fusion_k12_teacher/serve.py
  - docs/deploy.md
---

# 故障排查 / Troubleshooting

## 快速诊断 / Quick diagnosis

```bash
curl http://127.0.0.1:11448/api/health   # liveness + fusion-mlx 后端探测
curl http://127.0.0.1:11448/api/ready    # readiness
tail -f /tmp/fusion-k12-serve.log        # 后台启动日志（start.sh 默认日志文件）
./start.sh status 2>/dev/null || lsof -nP -iTCP:11448 -sTCP:LISTEN
```

## 启动问题 / Startup issues

### 1. `port 11448 not registered in port-registry.yaml — refusing to start`

`start.sh` 启动自检（issue #35）发现端口未注册。两种处理：

- fusion 全仓部署：在 `~/fusion/architecture/port-registry.yaml` 为 `fusion-k12-teacher` 注册 `port: 11448`
- 独立部署（无 registry 文件仅告警放行）：显式旁路 `FUSION_SKIP_REGISTRY_CHECK=1 ./start.sh start`

### 2. `FATAL: 缺 .venv — 先 source .venv/bin/activate && pip install -e .`

未建虚拟环境或未安装。执行：

```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -e .
```

### 3. 端口被残留进程占用，新配置不生效

旧进程未真正退出会静默占住 11448，新进程起不来，改任何配置都不生效。`start.sh` 已内置清理；手工处理：

```bash
./start.sh stop            # 等待端口释放，超时强制 kill -9
lsof -nP -iTCP:11448 -sTCP:LISTEN   # 确认已释放
```

### 4. cluster 模式启动抛 `NonDegradableError`

`FUSION_K12_MODE=cluster` 时缺失 `FUSION_K12_PG_DSN` 或 `asyncpg` 会 fail-closed（issue #36，无静默 SQLite 回退——多实例会脑裂）。补齐依赖与 DSN：`pip install -e ".[cluster]"`，设置 `FUSION_K12_PG_DSN`。单机使用请保持默认 standalone 模式。

## 鉴权与后端 / Auth and backend

### 5. `/api/health` 返回 401，GUI 仪表盘显示后端"不可达"

项目不自动加载 `.env`——必须经 `start.sh`（内部 `set -a; source .env`）注入 `FUSION_CLIENT_KEY`，否则对 gateway 鉴权失败。确认：

1. `.env` 中 `FUSION_CLIENT_KEY` 已填有效 gateway client key
2. 通过 `./start.sh start` 启动，而不是直接裸跑 `fusion-k12 serve`
3. `FUSION_PROFILE=prod` 时缺 key 直接拒绝启动（dev 缺省为匿名 + 警告）

### 6. health 探测 `backend` 非 ok（gateway/mlx 不通）

`/api/health` 的 backend 字段反映 fusion-mlx 链路。逐层排查：

```bash
curl http://127.0.0.1:11432/api/health    # fusion-gateway
curl http://127.0.0.1:11434/api/tags      # fusion-mlx（或经 gateway）
~/fusion/fusion-mlx/start.sh status       # 引擎状态
```

### 7. 云形态推理报错

`FUSION_MLX_CLOUD=1` 时必须显式设置 `FUSION_MLX_URL` 与 `FUSION_MLX_MODEL`（无 mlx 专属字段）。用 `FUSION_START_DRYRUN=1 ./startCloud.sh` 只跑预检定位配置缺失。

## Web GUI / Web GUI

### 8. 打开 `http://127.0.0.1:11448` 404 或空白

`serve.py` 挂载 `web/dist/`，目录不存在时跳过静态挂载（API-only）。构建：

```bash
cd web && pnpm install && pnpm build
./start.sh restart
```

开发热更可改用 Vite dev server：`cd web && pnpm dev`（`:5174`，API 代理到 `:11448`）。

### 9. 页面报引擎错误 / 骨架屏不消失

GUI 设计为优雅降级：引擎失败在结果区显示 error 标记与重试按钮。先看响应体与 `/tmp/fusion-k12-serve.log`；常见根因是第 5/6 条（鉴权或后端链路）。

### 10. 嵌入 union-shell 后登录页循环跳转

嵌入模式（`?embedded=1` + `window.parent !== window`）自动跳过自身登录、不发 `X-API-Key`（由 gateway 注入模块 key）。若仍跳转，检查 gateway 侧模块 key 配置与 `FUSION_SHELL_GATEWAY_URL` 注册是否成功（serve 启动日志有 shell 注册行；该能力 OFF 时不生效，standalone 不受影响）。

## 生成与推理 / Generation and inference

### 11. LLM 生成超时

Qwen3 thinking 模式开启时会产生数分钟 reasoning_content 致超时。默认已关闭（`enable_thinking=false`）；确认 `.env` 未误设 `FUSION_MLX_ENABLE_THINKING=true`。

### 12. 触发 429 限流

per-IP 滑动窗口限流，`.env` 中 `FUSION_K12_RATE_LIMIT`（如 `60/60` = 60 秒 60 次），留空关闭。该 key 在热更白名单内，改 `config/runtime`（`FUSION_K12_CONFIG_FILE` 指向的文件）保存即生效，无需重启。

### 13. 本地单卡 OOM / 推理排队

`FUSION_MLX_MAX_CONCURRENCY=1` 为严格串行（生产推荐），调大提高并发但增加 OOM 风险。此 key 启动注入，改动需重启。

## 数据与持久化 / Data and persistence

### 14. 数据在哪 / Where is my data

standalone 模式全部存本地 SQLite：`~/.fusion-k12/k12.db`（WAL，含 task_history / name_map / teachers / sessions / materials / audit_events 表）。备份该文件即可。

### 15. 改盐后历史匿名记录查不回

`FUSION_K12_SALT` 更换后旧 name_map 不可逆查。用 `fusion-k12 rotate-salt --show-versions` 轮换（旧版本保留供历史 ID 查询）；单机存量明文 name_map 用 `fusion-k12 encrypt-name-map --db <path>` 原地加密。

### 16. 配置改了不生效

热更仅限白名单：`FUSION_MLX_MODEL` / `FUSION_K12_RATE_LIMIT` / `FUSION_K12_SALT` / `FUSION_K12_LOG_LEVEL`，且需 `FUSION_K12_CONFIG_FILE` 指向配置文件（默认 5s 轮询）。其余（DB/端口/data_key）为启动注入，需 `./start.sh restart`。

## 观测与导出 / Observability

### 17. 审计与指标接口 403

`/api/audit/export` 与 `/api/metrics` 需要 admin key：请求头携带 `FUSION_K12_ADMIN_API_KEY` 对应的值。审计导出支持 `format=json|csv`、`since`、`limit≤10000`。

## 数字人 / Digital human

### 18. 数字人降级为 WS-only（无视频 / 静态头像）

预期降级路径，逐项检查：

1. `FUSION_K12_LIVEKIT_URL` / `FUSION_K12_LIVEKIT_API_KEY` / `FUSION_K12_LIVEKIT_API_SECRET` 已设置且 LiveKit SFU 可达
2. 已装 `pip install -e ".[digital-human]"`
3. 唇形同步（MuseTalk）另需 `.[digital-human-mlx]` 且仅 Apple Silicon；`FUSION_MLX_SOURCE` 指向 fusion-mlx 源码路径
4. 缺失任一项自动降级为 TTS 音频 + 静态头像，不影响其余功能
