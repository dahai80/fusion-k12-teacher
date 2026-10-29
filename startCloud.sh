#!/usr/bin/env bash
# fusion-k12-teacher 云端形态启动 (Ubuntu/任意 Linux + 云端大模型 API)
#
# 与 startLocal.sh (macOS 本地推理链) 构成双形态开关 — 对应迁移评估
# ~/fusion/architecture/fusion-k12-teacher-2-ubuntu-1012.md 的 local/cloud 双形态交付。
#
# 云端形态语义 (ai_client.py _cloud_mode):
#   FUSION_MLX_CLOUD=1 → ① 不注入 chat_template_kwargs (严格云厂商 4xx 拒绝)
#                        ② 不传 GBNF grammar (mlx 专属) ③ auto-select 关闭 (必须显式模型名)
#   LLM/TTS/ASR 全部指向 OpenAI 兼容云端点。
#
# 前置自检:
#   1. 必须显式配置 FUSION_MLX_MODEL (云模型名, 如 deepseek-chat) — 无 auto-select 兜底
#   2. .env 存在并注入
#   3. FUSION_MLX_CLOUD 强制置 1 (云端形态语义)
#   4. 云端点连通性提示 (不阻断 — 网络/配额问题由 #28 看门狗周期告警)
#
# 用法: ./startCloud.sh          前台启动
#       ./startCloud.sh -d       后台启动
#       ./startCloud.sh stop     停止
#       FUSION_START_DRYRUN=1 ./startCloud.sh   只打印形态/env 自检结果, 不启动

set -euo pipefail
cd "$(dirname "$0")"

die() { echo "FATAL: $*" >&2; exit 1; }

# 1) 平台提示 — Linux 为目标形态, macOS 上也能跑 (仅云 API, 无 mlx 依赖) 但非验收平台
if [ "$(uname)" = "Darwin" ]; then
  echo "⚠  当前在 macOS 上以云端形态启动 (仅用于联调)。生产 Ubuntu 形态请部署到 Linux。"
fi

# 2) env 注入
[ -f .env ] || die ".env 不存在。参考 .env.example 云端段落创建"
set -a
# shellcheck disable=SC1091
source .env
set +a
export FUSION_MLX_CLOUD=1   # 云端形态: 强制标准 OpenAI 兼容语义

# 3) 云端必备项校验 — auto-select 已禁用, 模型名缺失 = 运行时 404
[ -n "${FUSION_MLX_MODEL:-}" ] || die "云端形态必须显式设置 FUSION_MLX_MODEL (如 deepseek-chat / qwen-plus / glm-4-plus)"
echo "形态: cloud | LLM 端点: ${FUSION_MLX_URL:-(厂商默认)} | 模型: $FUSION_MLX_MODEL"
[ -n "${FUSION_CLIENT_KEY:-}" ] || echo "⚠  FUSION_CLIENT_KEY 未设置 — 云厂商将返回 401"

# 4) dry-run: 打印形态自检结果即退出
if [ "${FUSION_START_DRYRUN:-0}" = "1" ]; then
  echo "== dry-run (cloud 形态) =="
  echo "FUSION_MLX_URL=${FUSION_MLX_URL:-(厂商默认)}"
  echo "FUSION_MLX_MODEL=$FUSION_MLX_MODEL"
  echo "FUSION_CLIENT_KEY=$( [ -n "${FUSION_CLIENT_KEY:-}" ] && echo '(已设置)' || echo '(未设置!)')"
  echo "FUSION_MLX_CLOUD=$FUSION_MLX_CLOUD"
  echo "FUSION_MLX_TTS_URL=${FUSION_MLX_TTS_URL:-(同主端点)}"
  echo "FUSION_MLX_TTS_MODEL=${FUSION_MLX_TTS_MODEL:-(厂商默认)}"
  echo "FUSION_MLX_ASR_URL=${FUSION_MLX_ASR_URL:-(同主端点)}"
  echo "FUSION_MLX_ASR_MODEL=${FUSION_MLX_ASR_MODEL:-whisper-large-v3-turbo}"
  echo "== 检查通过, 实际启动请去掉 FUSION_START_DRYRUN =="
  exit 0
fi

exec ./start.sh "$@"
