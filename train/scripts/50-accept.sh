#!/usr/bin/env bash
# 50-accept.sh — 步骤 4：360 全量验收（serve 路径 + 微调 adapter, SFT 同分布 prompt）
# 通过标准：PRD math >= $ACCEPT_MIN_MATH（默认 89，对照 4B 基线 36）
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/00-env.sh"

OUT_DIR="$TRAIN_ROOT/data/04-评估集"
OUT_JSON="$OUT_DIR/accept_$(date +%m%d_%H%M).json"
LOG="$OUT_DIR/accept_$(date +%m%d_%H%M).log"

# 前置：验收对象是微调产物终态权重，不是底座，也不是训练中期 checkpoint
require_sft_done || exit 1

cd "$K12_ROOT"
source "$K12_ROOT/.venv/bin/activate" 2>/dev/null || log_warn "k12 venv 未找到，用当前 PATH 的 python3"
log_ok "运行 360 全量验收（serve 路径, adapter=$ADAPTER_NAME, SFT prompt）…"
python3 scripts/e2e_bnup_eval.py --direct-mlx --stream \
  --model "$SFT_MODEL" \
  --adapters "$ADAPTER_DIR" \
  --prompt-style sft \
  --concurrency "${ACCEPT_CONCURRENCY:-2}" \
  --output "$OUT_JSON" 2>&1 | tee "$LOG"

# 从输出 JSON 提取 math_accuracy（0-100 刻度, 与 ACCEPT_MIN_MATH 同口径）
MATH=$(python3 -c "import json;print(json.load(open('$OUT_JSON'))['report']['math_accuracy'])" 2>/dev/null || echo "")
if [ -z "$MATH" ]; then
  log_warn "未能从 $OUT_JSON 解析 math_accuracy，请人工判读: $LOG"; exit 0
fi
PASS=$(python3 -c "print(1 if float('$MATH') >= float('$ACCEPT_MIN_MATH') else 0)")
if [ "$PASS" = "1" ]; then
  log_ok "360 验收通过: math=${MATH} >= ${ACCEPT_MIN_MATH}（PRD 达标，可进入发布）"
else
  log_err "360 验收不通过: math=${MATH} < ${ACCEPT_MIN_MATH}（按 guides/05 §3 失败分布定位）"
  exit 1
fi
