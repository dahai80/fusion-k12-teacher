#!/usr/bin/env bash
# 20-sft.sh — 步骤 1：SFT 训练（QLoRA-8bit r16, 5700 步）
# 产物：$ADAPTER_DIR/adapters.safetensors（最终步权重）
#
# 断点续跑（RESUME=1）：
#   RESUME=1 ./20-sft.sh    # 从最新 checkpoint 权重续跑（fusion-mlx #1182 / trainer #65）
#   语义：权重从 checkpoint 恢复（loss 快速回落），但 step 从 0 重计、
#   optimizer state 不恢复 —— 实际是"更好起点的新 5700 步周期"。
#   无 checkpoint 时 trainer 会响亮警告并从头开始。
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/00-env.sh"

RESUME="${RESUME:-0}"

# 已完成则跳过（RESUME=1 / FORCE_SFT=1 均放行）
# 注意: adapters.safetensors 在 checkpoint 期 (~step 100+) 就落盘, 文件在 ≠ 训完,
# 跳过判定必须以 jobs API 终态为准 (引擎重启后 job 丢才退回文件兜底)
if [ "${FORCE_SFT:-0}" != "1" ] && [ "$RESUME" != "1" ]; then
  case "$(sft_job_state)" in
    completed)
      if [ -s "$ADAPTER_DIR/adapters.safetensors" ]; then
        log_ok "SFT job=$ADAPTER_NAME 已 completed，跳过（FORCE_SFT=1 强制重跑 / RESUME=1 续跑）"
        exit 0
      fi
      log_warn "job completed 但产物缺失，继续走提交流程"
      ;;
    running)
      log_ok "SFT job=$ADAPTER_NAME 训练中（外部已提交，本脚本转入等待）"
      EXTERN_RUNNING=1
      ;;
    *)
      if [ -s "$ADAPTER_DIR/adapters.safetensors" ]; then
        log_ok "SFT 产物已存在（无 job 记录，引擎重启后 job 丢），跳过（FORCE_SFT=1 强制重跑 / RESUME=1 续跑）"
        exit 0
      fi
      ;;
  esac
fi

# 启动前预检
bash "$SCRIPT_DIR/10-check-env.sh" || { log_err "环境预检未通过"; exit 1; }

# RESUME 预检：本地探测最新 checkpoint（与 trainer 内部 find_latest_checkpoint 同逻辑）
RESUME_ARGS=()
if [ "$RESUME" = "1" ]; then
  LATEST_CKPT=$(ls -1 "$ADAPTER_DIR"/*_adapters.safetensors 2>/dev/null \
    | grep -E '/[0-9]+_adapters\.safetensors$' | sort | tail -1)
  if [ -n "$LATEST_CKPT" ]; then
    CKPT_STEP=$(basename "$LATEST_CKPT" | sed -E 's/^0*([0-9]+)_adapters\.safetensors$/\1/')
    log_ok "RESUME=1：发现 checkpoint step=$CKPT_STEP ($(basename "$LATEST_CKPT"))，将以该权重为起点续跑"
    RESUME_ARGS=(--resume)
  else
    log_warn "RESUME=1 但 $ADAPTER_DIR 下无数字 checkpoint，将从头训练"
  fi
fi

if [ "${EXTERN_RUNNING:-0}" = "1" ]; then
  log_ok "跳过提交（job 已在跑）"
else
  cd "$FT_ROOT"
  # 训练用 monorepo 根 venv (fusion-trainer 装在那里)
  source /Users/dahai/fusion/.venv/bin/activate 2>/dev/null || log_warn "monorepo venv 未找到，用当前 PATH 的 python3"
  if [ "$RESUME" = "1" ] && [ ${#RESUME_ARGS[@]} -gt 0 ]; then
    log_ok "启动 SFT 训练（续跑自 step=$CKPT_STEP 权重）: iters=$SFT_ITERS model=$SFT_MODEL run=$ADAPTER_NAME"
  else
    log_ok "启动 SFT 训练: iters=$SFT_ITERS model=$SFT_MODEL run=$ADAPTER_NAME"
  fi
  # ft sft + --run-name: adapter 名不覆写 v1; 数据/超参来自 SFT_CONFIG (materials 归档副本)
  FUSION_MLX_PORT="$MLX_PORT" FUSION_MLX_ADMIN_TOKEN="$MLX_ADMIN_KEY" \
    python3 -m fusion_trainer.cli sft \
    --config "$SFT_CONFIG" \
    --model "$SFT_MODEL" \
    --dataset "$SFT_DATA" \
    --run-name "$ADAPTER_NAME" \
    "${RESUME_ARGS[@]}" 2>&1 | tee "$TRAIN_ROOT/data/99-状态与恢复/sft_$(date +%m%d_%H%M).log"
fi

# 轮询该 adapter 的 job 直到非 running（job 由引擎持有，trainer 退出后查终态）
sleep 60
while :; do
  ST=$(sft_job_state)
  [ "$ST" != "running" ] && [ "$ST" != "api_err" ] && break
  [ "$ST" = "api_err" ] && log_warn "jobs API 暂不可达，重试"
  sleep 300
done

# 完成判定：job 终态 completed 且终态权重落盘（文件在 ≠ 完成，checkpoint 期就有）
sleep 30
if [ "$ST" = "completed" ] && [ -s "$ADAPTER_DIR/adapters.safetensors" ]; then
  log_ok "SFT 完成: $ADAPTER_DIR/adapters.safetensors"
  cp "$ADAPTER_DIR/adapters.safetensors" "$TRAIN_ROOT/checkpoints/bnup_sft_32b_final.safetensors" 2>/dev/null
else
  log_err "SFT 结束但终态无效: job_state=${ST}（可能被中断，见 guides/99；无 job 记录时人工确认后 FORCE_SFT=1/RESUME=1 处理）"
  exit 1
fi
