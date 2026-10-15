#!/usr/bin/env bash
# 10-check-env.sh — 步骤 0：环境与依赖预检（所有前置一次性查完，失败即停）
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/00-env.sh"

FAIL=0
need() { command -v "$1" >/dev/null 2>&1 || { log_err "缺少命令: $1"; FAIL=1; }; }
need python3; need curl; need shasum; need jq 2>/dev/null || true

# 1) mlx 引擎
if curl -s -m 5 "$MLX_BASE_URL/" -H "Authorization: Bearer $MLX_ADMIN_KEY" >/dev/null 2>&1; then
  log_ok "mlx 引擎在线 ($MLX_BASE_URL)"
else
  log_warn "mlx 引擎不在线，尝试 start.sh start …"
  bash "$MLX_ROOT/start.sh" start >/dev/null 2>&1
  sleep 15
  curl -s -m 5 "$MLX_BASE_URL/" -H "Authorization: Bearer $MLX_ADMIN_KEY" >/dev/null 2>&1 \
    && log_ok "mlx 引擎已拉起" || { log_err "mlx 引擎拉起失败"; FAIL=1; }
fi

# 2) admin key
[ -n "$MLX_ADMIN_KEY" ] && log_ok "MLX_ADMIN_KEY 已从 settings.json 读取" \
  || { log_err "MLX_ADMIN_KEY 为空（settings.json auth.api_key 缺失）"; FAIL=1; }

# 3) 底座快照
SNAP=$(ls -d "$SNAPSHOT_DIR"/*/ 2>/dev/null | head -1)
[ -n "$SNAP" ] && log_ok "底座快照: $SNAP" || { log_err "底座快照缺失: $SNAPSHOT_DIR"; FAIL=1; }

# 4) 数据集冻结校验
for f in "$SFT_DATA" "$DPO_DATA"; do
  [ -s "$f" ] && log_ok "数据集存在: $(basename "$f") ($(wc -l < "$f" | tr -d ' ') 行)" \
    || { log_err "数据集缺失: $f"; FAIL=1; }
done
SUMS="$TRAIN_ROOT/SHA256SUMS.txt"
if [ -f "$SUMS" ] && (cd "$TRAIN_ROOT" && shasum -a 256 -c SHA256SUMS.txt --quiet >/dev/null 2>&1); then
  log_ok "SHA256 全量校验通过"
else
  log_warn "SHA256 校验未通过或文件缺失（继续，但建议先跑 shasum -c）"
fi

# 5) trainer 环境
python3 -c "import fusion_trainer" 2>/dev/null \
  && log_ok "fusion_trainer 可导入" \
  || { log_warn "当前 shell 无 fusion_trainer（20-sft/40-dpo 启动前会 source monorepo 根 venv）"; }

# 6) 无"外部"训练在跑（本线 ADAPTER_NAME 的 job 除外——20-sft.sh 等待路径会接管它）
FOREIGN_RUNNING=$(curl -s -m 10 "$MLX_BASE_URL/admin/api/fine-tune/jobs" \
  -H "Authorization: Bearer $MLX_ADMIN_KEY" -H "X-Fusion-Route: admin" 2>/dev/null \
  | python3 -c "import json,sys;d=json.load(sys.stdin);jobs=d if isinstance(d,list) else d.get('jobs',[]);print(sum(1 for j in jobs if j.get('status')=='running' and j.get('adapter_name')!='$ADAPTER_NAME'))" 2>/dev/null || echo "?")
[ "$FOREIGN_RUNNING" = "0" ] && log_ok "无外部 running 训练 job（本线 ${ADAPTER_NAME} 除外）" || { log_err "存在外部 running 训练 job（${FOREIGN_RUNNING}），先处理再跑"; FAIL=1; }

# 7) 内存净空（红线 3：无 >32GB 的共存进程）
TOP_PID=$(ps aux | sort -k6 -rn | sed -n '2p')
TOP_KB=$(echo "$TOP_PID" | awk '{print $6}')
TOP_NAME=$(echo "$TOP_PID" | awk '{for(i=11;i<=NF;i++) printf "%s ", $i; print ""}' | cut -c1-50)
if [ "${TOP_KB:-0}" -gt $((32*1048576)) ]; then
  log_warn "存在大内存共存进程（$(echo "scale=1; $TOP_KB/1048576" | bc)GB): $TOP_NAME — 训练期争抢风险"
fi

exit $FAIL
