---
doc_id: fusion-k12-teacher/get-started
product: fusion-k12-teacher
class: app
entry: guided-ui
doc_type: get-started
title: { zh: "Fusion-K12-Teacher 快速上手", en: "Fusion-K12-Teacher get started" }
audience: engineer
status: draft
version: 2.2.6
updated: 2026-11-07
owner: "@dahai"
source_of_truth:
  - README.md
  - start.sh
  - .env.example
  - web/package.json
---

# 快速上手 / Get Started

## 前置条件 / Prerequisites

- macOS Apple Silicon（本地形态）或 Linux（云形态）
- Python 3.11+
- 推理后端二选一：
  - 本地：fusion-mlx 运行在 `http://localhost:11432`（`~/fusion/fusion-mlx/start.sh start`），前置 fusion-gateway（`:11432`）
  - 云端：任意 OpenAI 兼容 API（`.env` 设 `FUSION_MLX_CLOUD=1` + `FUSION_MLX_URL` + `FUSION_MLX_MODEL`）
- 网关鉴权 key（`FUSION_CLIENT_KEY`，经 fusion-core 单点解析）

## 安装 / Install

```bash
git clone https://github.com/dahai80/fusion-k12-teacher.git
cd fusion-k12-teacher
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

可选 extras（按需）：`.[math]`（数学课程平台）、`.[web]`、`.[cluster]`（Postgres 集群）、`.[digital-human]`（数字人，跨平台）、`.[digital-human-mlx]`（MuseTalk 唇形同步，仅 Apple Silicon）。

## 配置 / Configure

```bash
cp .env.example .env
# 编辑 .env，至少设置：
#   FUSION_CLIENT_KEY=<fusion-gateway client key>   # 缺失时 dev 模式匿名+警告，prod 模式拒绝启动
#   FUSION_MLX_MODEL=<模型名>
```

完整环境变量清单见 `.env.example` 与 [troubleshooting.md](troubleshooting.md)。

## 构建 Web GUI（可选）/ Build web GUI (optional)

`serve.py` 挂载 `web/dist/`；不构建则 API-only（开发可用 Vite dev server）。

```bash
cd web && pnpm install && pnpm build   # 输出 web/dist/
```

## 启动 / Start

```bash
./start.sh start          # 后台启动，日志 /tmp/fusion-k12-serve.log
./start.sh stop           # 停止
./start.sh restart        # 重启
./start.sh                # 前台启动（Ctrl+C 停止）
```

`start.sh` 会：校验端口 11448 已注册进 `architecture/port-registry.yaml`（缺失 registry 文件仅告警放行，standalone 部署可用 `FUSION_SKIP_REGISTRY_CHECK=1` 旁路）→ 清理残留进程 → 注入 `.env` → 启动 `fusion-k12 serve` → 健康检查直到 `backend=ok`。

## 验证 / Verify

```bash
curl http://127.0.0.1:11448/api/health
# 期望 {"backend":"ok",...}
```

浏览器打开 `http://127.0.0.1:11448` 进入教师 Web GUI（仪表盘 → 备课 → 批改 → 学情分析等 10 个分区）。

## 第一个任务 / First task

GUI 方式：登录/设置 API key 后，进入「备课」分区，选择学科、年级、课题，点击生成。

CLI 方式：

```bash
fusion-k12 lesson plan 数学 三年级 长方形周长
fusion-k12 --version      # 查看版本
fusion-k12 --help         # 命令总览
```

## 下一步 / Next steps

- 全部 CLI 命令与 HTTP API：[api.md](api.md) 与 README 模块章节
- 部署到 Docker Compose / K8s：[deploy.md](deploy.md)
- 故障排查：[troubleshooting.md](troubleshooting.md)
