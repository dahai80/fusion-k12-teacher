#!/usr/bin/env bash
# fusion-k12-teacher 本地形态启动 (macOS + fusion-mlx/gateway 本地推理链)
#
# 与 startCloud.sh (Ubuntu 云端) 构成双形态开关 — 对应迁移评估
# ~/fusion/architecture/fusion-k12-teacher-2-ubuntu-1012.md 的 local/cloud 双形态交付。
#
# 前置自检:
#   1. 必须运行在 macOS (mlx 仅支持 Apple Silicon)
#   2. .env 存在并注入 (项目不自动加载 .env — 见 start.sh 落地经验)
#   3. FUSION_MLX_CLOUD 强制归零 (本地形态语义)
#   4. fusion-mlx :11434 / gateway :11432 可达性提示 (未起仅警告, 不阻断)
#
# 用法: ./startLocal.sh          同 ./start.sh (前台启动)
#       ./startLocal.sh -d       后台启动
#       ./startLocal.sh stop     停止
#       FUSION_START_DRYRUN=1 ./startLocal.sh   只打印形态/env 自检结果, 不启动

set -euo pipefail
cd "$(dirname "$0")"

die() { echo "FATAL: $*" >&2; exit 1; }

# 1) 平台检查 — 本地形态依赖 mlx (Apple Silicon 专属)
[ "$(uname)" = "Darwin" ] || die "startLocal.sh 仅支持 macOS (检测到 $(uname))。Ubuntu 请用 ./startCloud.sh"

# 2) env 注入 — start.sh 不会自动加载 .env
[ -f .env ] || die ".env 不存在。参考 .env.example 创建 (本地形态必配 FUSION_CLIENT_KEY/MODEL)"
set -a
# shellcheck disable=SC1091
source .env
set +a
export FUSION_MLX_CLOUD=0   # 本地形态: 强制走 mlx 语义 (chat_template_kwargs/grammar/auto-select)

# 3) 依赖服务可达性提示 (不阻断 — 允许先起 serve 再起 mlx)
if ! curl -s -m 3 -o /dev/null http://127.0.0.1:11434/ 2>/dev/null; then
  echo "⚠  fusion-mlx :11434 不可达 — LLM/TTS/ASR 将不可用。先启动: ~/fusion/fusion-mlx/start.sh start"
fi
if ! curl -s -m 3 -o /dev/null http://127.0.0.1:11432/v1/models 2>/dev/null; then
  echo "⚠  fusion-gateway :11432 不可达 — 先启动: ~/fusion/fusion-gateway/start-gateway.sh start"
fi

# 4) dry-run: 打印形态自检结果即退出 (CI/运维核对用)
if [ "${FUSION_START_DRYRUN:-0}" = "1" ]; then
  echo "== dry-run (local 形态) =="
  echo "FUSION_MLX_URL=${FUSION_MLX_URL:-http://localhost:11432/v1}"
  echo "FUSION_MLX_MODEL=${FUSION_MLX_MODEL:-(auto-select)}"
  echo "FUSION_MLX_CLOUD=$FUSION_MLX_CLOUD"
  echo "FUSION_MLX_TTS_URL=${FUSION_MLX_TTS_URL:-(同主端点)}"
  echo "FUSION_MLX_TTS_MODEL=${FUSION_MLX_TTS_MODEL:-kokoro-82m}"
  echo "== 检查通过, 实际启动请去掉 FUSION_START_DRYRUN =="
  exit 0
fi

exec ./start.sh "$@"
