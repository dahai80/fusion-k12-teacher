#!/usr/bin/env bash
# run_all.sh — 一键启动：微调全链（预检 → SFT → 中评 gate → DPO → 360 验收）
#
# 用法:
#   ./run_all.sh              # 从头跑全链（每步产物存在则自动跳过，断点续跑）
#   ./run_all.sh --from mid   # 从中评 gate 开始（跳过 SFT）
#   ./run_all.sh --dry-run    # 只做预检与产物检查，不实际训练/评测
#   ./run_all.sh --resume     # 等价于逐段检查产物后从缺口处继续（默认行为）
#
# 环境变量（均可覆盖，见 00-env.sh）:
#   FORCE_SFT=1          强制重跑 SFT
#   GATE_MIN_EVAL_EXEC=85 中评阈值   ACCEPT_MIN_MATH=89 验收阈值
#   SFT_ITERS=5700       训练步数   DPO_DONE=1 跳过 DPO
#
# 步骤: check → sft → midgate → dpo → accept
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/00-env.sh"

FROM="check"
DRY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --from) FROM="$2"; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    --resume) FROM="check"; shift ;;
    -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
    *) log_err "未知参数: $1"; exit 2 ;;
  esac
done

ORDER=(check sft midgate dpo accept)
STARTED=0
for S in "${ORDER[@]}"; do
  [ "$STARTED" = "0" ] && [ "$S" != "$FROM" ] && continue
  STARTED=1

  echo ""
  echo "=============================================="
  echo "▶ 步骤: $S  ($(date '+%m-%d %H:%M:%S'))"
  echo "=============================================="

  if [ "$DRY" = "1" ]; then
    case "$S" in
      check)   bash "$SCRIPT_DIR/10-check-env.sh" || exit 1 ;;
      sft)     [ -s "$ADAPTER_DIR/adapters.safetensors" ] && log_ok "[DRY] SFT 产物在位，将跳过" || log_warn "[DRY] SFT 将实际执行（5700 步，~10h）" ;;
      midgate) [ -s "$ADAPTER_DIR/adapters.safetensors" ] && log_ok "[DRY] 中评 gate 就绪（28 题）" || log_warn "[DRY] SFT 未完成，gate 将被跳过" ;;
      dpo)     [ "${DPO_DONE:-0}" = "1" ] && log_ok "[DRY] DPO_DONE=1，将跳过" || log_warn "[DRY] DPO 将实际执行" ;;
      accept)  log_ok "[DRY] 360 验收就绪（--direct-mlx）" ;;
    esac
    continue
  fi

  case "$S" in
    check)   bash "$SCRIPT_DIR/10-check-env.sh" || { log_err "预检失败，终止"; exit 1; } ;;
    sft)     bash "$SCRIPT_DIR/20-sft.sh"        || { log_err "SFT 失败，终止（ guides/99 §B2 恢复）"; exit 1; } ;;
    midgate) bash "$SCRIPT_DIR/30-midgate.sh"    || { log_err "中评 gate 未通过，终止"; exit 1; } ;;
    dpo)     bash "$SCRIPT_DIR/40-dpo.sh"        || { log_err "DPO 失败，终止"; exit 1; } ;;
    accept)  bash "$SCRIPT_DIR/50-accept.sh"     || { log_err "360 验收未通过"; exit 1; } ;;
  esac
  log_ok "步骤 $S 完成"
done

echo ""
log_ok "全链执行完毕 ✓（结果与产物见 train/data/04-评估集/ 与 train/checkpoints/）"
