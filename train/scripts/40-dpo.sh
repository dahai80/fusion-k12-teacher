#!/usr/bin/env bash
# 40-dpo.sh — 步骤 3：DPO 训练（β=0.1，链式 SFT adapter）
# 产物：DPO adapter 目录（路径由 fusion-trainer 输出，记录到 STATUS.md）
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/00-env.sh"

if [ "${DPO_DONE:-0}" = "1" ]; then
  log_ok "DPO_DONE=1，跳过（如需重跑置 0）"
  exit 0
fi

# 前置：SFT 产物
[ -s "$ADAPTER_DIR/adapters.safetensors" ] \
  || { log_err "SFT 产物缺失，先跑 20-sft.sh"; exit 1; }

cd "$FT_ROOT"
# 训练用 monorepo 根 venv (fusion-trainer 装在那里)
source /Users/dahai/fusion/.venv/bin/activate 2>/dev/null || log_warn "monorepo venv 未找到，用当前 PATH 的 python3"
log_ok "启动 DPO 训练（链式 SFT adapter=$ADAPTER_NAME, β=0.1）…"
FUSION_MLX_PORT="$MLX_PORT" FUSION_MLX_ADMIN_TOKEN="$MLX_ADMIN_KEY" \
  python3 -m fusion_trainer.cli bnup-train --stage dpo \
    --model "$SFT_MODEL" \
    --sft-data "$SFT_DATA" \
    --dpo-data "$DPO_DATA" \
    --init-adapter-path "$ADAPTER_DIR" 2>&1 | tee "$TRAIN_ROOT/data/99-状态与恢复/dpo_$(date +%m%d_%H%M).log"

# DPO 完成判定：trainer 退出后无 running job，且 30 分钟内 jobs API 稳定
sleep 60
while :; do
  RUNNING=$(curl -s -m 15 "$MLX_BASE_URL/admin/api/fine-tune/jobs" \
    -H "Authorization: Bearer $MLX_ADMIN_KEY" -H "X-Fusion-Route: admin" \
    | python3 -c "import json,sys;d=json.load(sys.stdin);jobs=d if isinstance(d,list) else d.get('jobs',[]);print(sum(1 for j in jobs if j.get('status')=='running'))" 2>/dev/null || echo "err")
  [ "$RUNNING" = "0" ] && break
  [ "$RUNNING" = "err" ] && { sleep 30; continue; }
  sleep 300
done
log_ok "DPO 训练结束（adapter 路径见日志，人工确认后置 DPO_DONE=1 并写入 STATUS.md）"
