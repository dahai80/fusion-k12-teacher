#!/usr/bin/env bash
# fusion-k12-teacher serve 启动脚本
#
# 落地经验（勿删）：
# 1. 项目不自动加载 .env — 必须显式 set -a 注入 FUSION_MLX_API_KEY/MODEL，
#    否则 /api/health 对 gateway 401 → dashboard 显示"不可达"
# 2. 重启必须等旧进程真正退出（lsof 验证端口释放），普通 kill 可能杀不死
#    （残留旧进程占 11448 → 新进程起不来 → 配置怎么改都不生效）
# 3. 起完后打 /api/health 确认 backend=ok 才算成功
#
# 用法: ./start.sh          前台启动（Ctrl+C 停止）
#       ./start.sh -d       后台启动（日志 /tmp/fusion-k12-serve.log）
#       ./start.sh stop     停止并确认端口释放

set -euo pipefail
cd "$(dirname "$0")"

PORT="${FUSION_K12_PORT:-11448}"
LOG_FILE="${FUSION_K12_LOG:-/tmp/fusion-k12-serve.log}"
VENV=".venv"

port_pids() { lsof -t -nP -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true; }

wait_port_free() { # $1=超时秒
  for _ in $(seq 1 "$1"); do
    [ -z "$(port_pids)" ] && return 0
    sleep 1
  done
  return 1
}

stop_server() {
  local pids; pids="$(port_pids)"
  [ -z "$pids" ] && { echo "serve 未在运行 (端口 $PORT 空闲)"; return 0; }
  echo "停止 serve (pid: $(echo $pids | tr '\n' ' '))"
  kill $pids 2>/dev/null || true
  wait_port_free 10 && { echo "端口 $PORT 已释放"; return 0; }
  echo "普通 kill 超时，强制终止..."
  kill -9 $(port_pids) 2>/dev/null || true
  wait_port_free 5 || { echo "FATAL: 端口 $PORT 无法释放"; exit 1; }
  echo "端口 $PORT 已释放 (force)"
}

cmd_stop() { stop_server; }

cmd_start() {
  [ -x "$VENV/bin/fusion-k12" ] || { echo "FATAL: 缺 $VENV — 先 source $VENV/bin/activate && pip install -e ."; exit 1; }
  [ -f .env ] || echo "WARN: 无 .env — gateway 鉴权可能 401"

  # 残留旧进程：上次教训 — 不清掉会静默占端口，新进程配置永不生效
  local stale; stale="$(port_pids)"
  if [ -n "$stale" ]; then
    echo "发现残留进程 (pid: $(echo $stale | tr '\n' ' '))，先停止..."
    stop_server
  fi

  # env 注入：项目不自动加载 .env（根因之一）
  set -a; [ -f .env ] && source .env; set +a

  if [ "${1:-}" = "-d" ]; then
    nohup "$VENV/bin/fusion-k12" serve > "$LOG_FILE" 2>&1 < /dev/null &
    echo "后台启动中 (日志 $LOG_FILE)..."
  else
    echo "前台启动 (Ctrl+C 停止)..."
    exec "$VENV/bin/fusion-k12" serve
  fi

  # 健康检查：backend=ok 才算成功（gateway 鉴权 + mlx 探测全通）
  for i in $(seq 1 20); do
    sleep 1
    local body
    body="$(curl -s -m 5 "http://127.0.0.1:$PORT/api/health" 2>/dev/null || true)"
    case "$body" in
      *'"backend":"ok"'*)
        echo "serve 就绪: http://127.0.0.1:$PORT  ($body)"; return 0 ;;
      *'"backend"'*)
        echo "  [$i/20] 进程已起但 backend 未就绪: $body" ;;
      *) echo "  [$i/20] 等待启动..." ;;
    esac
  done
  echo "FATAL: 20s 内未就绪 — 查 $LOG_FILE"; exit 1
}

case "${1:-}" in
  stop)  cmd_stop ;;
  -d)    cmd_start -d ;;
  "")    cmd_start ;;
  *)     echo "用法: $0 [ | -d | stop]"; exit 1 ;;
esac
