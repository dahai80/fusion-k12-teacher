#!/usr/bin/env bash
# 30-midgate.sh — 步骤 2：中评 gate（serve 路径 28 题冒烟, SFT 同分布 prompt）
# 阈值：eval_exec >= $GATE_MIN_EVAL_EXEC（默认 85）；不过即停（gate 是硬门槛）
#
# 2026-10-16 起改走 serve（fusion-mlx :11434 + adapters 挂载 + --stream SSE）：
# 旧"引擎外直载"根因（TurboQuant 4-bit KV 乱码, fusion-mlx#1230）已在
# ~/.fusion-mlx/model_settings.json per-model 关闭, serve 输出干净;
# 且 serve 即生产路径, gate 必须覆盖真实服务链路。
# 引擎外直载 runner 保留在 scripts/03-中评gate/midgate_direct_lm.py 仅作 fallback。
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/00-env.sh"

OUT_JSON="$TRAIN_ROOT/data/04-评估集/midgate_$(date +%m%d_%H%M).json"
LOG="$TRAIN_ROOT/data/99-状态与恢复/midgate_$(date +%m%d_%H%M).log"

# 前置：SFT 训练终态闸门 (adapters.safetensors 在 checkpoint 期就落盘, 文件在 ≠ 训完;
# 且训练期间发推理请求会争抢内存触发 fatal_exit, 见 guides/99 §B1)
require_sft_done || exit 1

# 前置：32B 必须已关 TurboQuant KV（#1230），否则输出乱码
TQ=$(python3 -c "
import json,os
p=os.path.expanduser('~/.fusion-mlx/model_settings.json')
try: m=json.load(open(p))
except Exception: print('missing'); raise SystemExit
print(m.get('models',{}).get('$SFT_MODEL',{}).get('turboquant_kv_enabled','unset'))
" 2>/dev/null || echo "missing")
if [ "$TQ" != "False" ]; then
  log_err "model_settings.json 未对 $SFT_MODEL 关闭 turboquant_kv_enabled (当前: $TQ) — 先按 guides/99 §乱码 行配置并重启 fusion-mlx"
  exit 1
fi

cd "$K12_ROOT"
source "$K12_ROOT/.venv/bin/activate" 2>/dev/null || log_warn "k12 venv 未找到，用当前 PATH 的 python3"
log_ok "运行中评 gate（serve 路径, adapter=$ADAPTER_NAME, 28 题, SFT prompt）…"
python3 scripts/e2e_bnup_eval.py --direct-mlx --stream \
  --model "$SFT_MODEL" \
  --adapters "$ADAPTER_DIR" \
  --testset "$E2E_TESTSET" \
  --prompt-style sft \
  --concurrency "${GATE_CONCURRENCY:-2}" \
  --output "$OUT_JSON" 2>&1 | tee "$LOG"

# 从输出 JSON 提取 eval_exec_rate（0-100 刻度, 与 GATE_MIN_EVAL_EXEC 同口径）
EVAL_EXEC=$(python3 -c "import json;print(json.load(open('$OUT_JSON'))['report']['eval_exec_rate'])" 2>/dev/null || echo "")
if [ -z "$EVAL_EXEC" ]; then
  log_warn "未能从 $OUT_JSON 解析 eval_exec_rate，请人工判读: $LOG"
  [ "${GATE_AUTOFAIL:-1}" = "1" ] && { log_err "GATE_AUTOFAIL=1：按不通过处理"; exit 1; }
  exit 0
fi

PASS=$(python3 -c "print(1 if float('$EVAL_EXEC') >= float('$GATE_MIN_EVAL_EXEC') else 0)")
if [ "$PASS" = "1" ]; then
  log_ok "中评 gate 通过: eval_exec=$EVAL_EXEC >= $GATE_MIN_EVAL_EXEC"
  MATH=$(python3 -c "import json;print(json.load(open('$OUT_JSON'))['report']['math_accuracy'])" 2>/dev/null || echo "?")
  log_ok "参考: math=${MATH}（4B 基线 42.9, 应显著提升）"
else
  log_err "中评 gate 不通过: eval_exec=${EVAL_EXEC} < ${GATE_MIN_EVAL_EXEC}（按 guides/03 §5 回改数据后重跑 20-sft.sh）"
  exit 1
fi
