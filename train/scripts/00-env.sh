#!/usr/bin/env bash
# 00-env.sh — 环境变量与路径定义（被所有脚本 source，不单独执行）
# 一键启动的单一事实源：改路径/改 key 只动这里。

export TRAIN_ROOT="${TRAIN_ROOT:-$HOME/fusion/fusion-k12-teacher/train}"
export FT_ROOT="${FT_ROOT:-$HOME/fusion/fusion-trainer}"
export MLX_ROOT="${MLX_ROOT:-$HOME/fusion/fusion-mlx}"
export K12_ROOT="${K12_ROOT:-$HOME/fusion/fusion-k12-teacher}"

# mlx admin key：只从 settings.json 读，绝不写死
export MLX_ADMIN_KEY="${MLX_ADMIN_KEY:-$(python3 -c "import json;print(json.load(open('$HOME/.fusion-mlx/settings.json')).get('auth',{}).get('api_key',''))" 2>/dev/null)}"
export MLX_PORT="${MLX_PORT:-11434}"
export MLX_BASE_URL="http://127.0.0.1:${MLX_PORT}"

# 底座与数据
export SFT_MODEL="${SFT_MODEL:-mlx-community--Qwen2.5-32B-Instruct-4bit}"
export SFT_DATA="${SFT_DATA:-$TRAIN_ROOT/data/02-SFT/sft_v1.jsonl}"
export DPO_DATA="${DPO_DATA:-$TRAIN_ROOT/data/03-DPO/dpo_v1.jsonl}"
# v1 (bnup_sft_32b) 无效已弃: trainer 丢 Alpaca system 字段 (fusion-trainer#69/PR#70),
# serving 恒插 system → 分布不匹配。v2 起含 system 训练。
export ADAPTER_NAME="${ADAPTER_NAME:-bnup_sft_32b_v2}"
export ADAPTER_DIR="$HOME/.fusion-mlx/adapters/${SFT_MODEL}/${ADAPTER_NAME}"
export SFT_CONFIG="${SFT_CONFIG:-$TRAIN_ROOT/materials/03-SFT训练/bnup_sft_32b.yaml}"
export E2E_TESTSET="${E2E_TESTSET:-$TRAIN_ROOT/data/04-评估集/e2e_28.json}"
export SNAPSHOT_DIR="$HOME/.fusion-mlx/models/models--${SFT_MODEL}/snapshots"

# 步骤开关（gate 不过即停；FORCE=1 强行继续）
export SFT_ITERS="${SFT_ITERS:-5700}"
export GATE_MIN_EVAL_EXEC="${GATE_MIN_EVAL_EXEC:-85}"
export ACCEPT_MIN_MATH="${ACCEPT_MIN_MATH:-89}"
# SFT 断点续跑：RESUME=1 时 20-sft.sh 透传 --resume（fusion-mlx #1182 权重级续跑，
# step 从 0 重计、optimizer state 不恢复；无 checkpoint 自动从头）
export RESUME="${RESUME:-0}"

# 颜色输出
export C_G="\033[32m"; export C_R="\033[31m"; export C_Y="\033[33m"; export C_N="\033[0m"
log_ok()  { echo -e "${C_G}[OK]${C_N} $*"; }
log_err() { echo -e "${C_R}[ERR]${C_N} $*" >&2; }
log_warn(){ echo -e "${C_Y}[WARN]${C_N} $*"; }

# SFT job 终态判定: adapters.safetensors 在 checkpoint 期 (~step 100+) 就落盘,
# 文件存在 ≠ 训练完成。必须查 jobs API: 该 adapter_name 的 job 是否 completed 且无 running。
sft_job_state() {
  curl -s -m 15 "$MLX_BASE_URL/admin/api/fine-tune/jobs" \
    -H "Authorization: Bearer $MLX_ADMIN_KEY" \
    | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
except Exception:
    print('api_err'); raise SystemExit
jobs=d if isinstance(d,list) else d.get('jobs',[])
mine=[j for j in jobs if j.get('adapter_name')=='$ADAPTER_NAME']
if not mine:
    print('no_job'); raise SystemExit
st=[j.get('status') for j in mine]
if 'running' in st: print('running')
elif 'completed' in st: print('completed')
else: print(st[0])
" 2>/dev/null || echo "api_err"
}

# gate/accept 共用的完成闸门: 训练中一律拒绝 (训练期推理会触发 memory_enforcer fatal)
require_sft_done() {
  local STATE; STATE=$(sft_job_state)
  case "$STATE" in
    completed)
      [ -s "$ADAPTER_DIR/adapters.safetensors" ] \
        || { log_err "job completed 但 $ADAPTER_DIR/adapters.safetensors 缺失 (引擎重启后 job 丢, 人工确认)"; return 1; }
      log_ok "SFT job=$ADAPTER_NAME completed, 终态权重在位"
      ;;
    running)
      log_err "SFT job=$ADAPTER_NAME 还在训练 (adapters.safetensors 是 checkpoint 期权重, 非终态); 训练期间禁止推理 (争抢触发 fatal_exit, 见 guides/99 §B1)"
      return 1
      ;;
    *)
      log_warn "jobs API 查不到 $ADAPTER_NAME 的 job (state=$STATE; 引擎重启后 job 内存态丢失)"
      if [ "${ALLOW_NO_JOB_RECORD:-0}" != "1" ]; then
        log_err "默认拒绝执行; 人工确认终态后 ALLOW_NO_JOB_RECORD=1 放行"
        return 1
      fi
      [ -s "$ADAPTER_DIR/adapters.safetensors" ] \
        || { log_err "SFT 产物缺失: $ADAPTER_DIR/adapters.safetensors"; return 1; }
      log_warn "ALLOW_NO_JOB_RECORD=1: 按 adapters.safetensors 存在放行 (风险自担)"
      ;;
  esac
}
