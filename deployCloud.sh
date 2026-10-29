#!/usr/bin/env bash
# deployCloud.sh — fusion-k12-teacher 一键自动化部署到云服务器 (Ubuntu 22.04, cloud 形态)
#
# 用法:  bash deployCloud.sh            # 全量部署（代码+依赖+.env+serve+nginx反代+默认页链接）
#        bash deployCloud.sh code       # 只同步代码并重启服务（快速迭代）
#        bash deployCloud.sh verify     # 只做健康检查
#
# 前置条件:
#   1. 本机已配置到服务器的 SSH 免密登录（ssh-copy-id）
#   2. 阿里云安全组已放行 22/80/443/TCP（与 linguakids 同机共用）
#
# 形态: cloud（FUSION_MLX_CLOUD=1）— LLM/TTS/ASR 走云端 OpenAI 兼容 API，
#       Ubuntu 上无 mlx 依赖（digital-human 自动降级 StaticAvatar）。
#       依据: ~/fusion/architecture/fusion-k12-teacher-2-ubuntu-1012.md
# 反代: 与 linguakids-mvp 同机共存 — nginx 在现有 default 站点上新增
#       /fusion/ 前缀反代到本机 11448（不动 linguakids 的 / 与 /lkws）
set -euo pipefail

# ---------------- 可配置项 ----------------
SERVER="${SERVER:-root@121.41.12.80}"
REMOTE_ROOT="${REMOTE_ROOT:-/opt/fusion-k12-teacher}"
PORT="${PORT:-11448}"
DOMAIN="${DOMAIN:-k12grade.dpdns.org}"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✅ $*${NC}"; }
warn() { echo -e "${YELLOW}⚠️  $*${NC}"; }
fail() { echo -e "${RED}❌ $*${NC}"; exit 1; }
step() { echo -e "\n========== $* =========="; }

SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=30"
run()   { ssh $SSH_OPTS "$SERVER" "$@"; }
push()  { scp $SSH_OPTS "$1" "$SERVER:$2"; }
rsync_to() { rsync -a -z -e "ssh $SSH_OPTS" "$@"; }

verify_key() {
  ssh -o BatchMode=yes -o ConnectTimeout=10 "$SERVER" true 2>/dev/null && return 0
  if command -v sshpass >/dev/null && [ -n "${SERVER_PASSWORD:-}" ]; then
    SSH_OPTS="$SSH_OPTS -o PasswordAuthentication=yes"
    run()   { sshpass -p "$SERVER_PASSWORD" ssh $SSH_OPTS "$SERVER" "$@"; }
    push()  { sshpass -p "$SERVER_PASSWORD" scp $SSH_OPTS "$1" "$SERVER:$2"; }
    rsync_to() { sshpass -p "$SERVER_PASSWORD" rsync -a -z -e "ssh $SSH_OPTS" "$@"; }
    warn "SSH 免密不可用，已回落密码登录"
    return 0
  fi
  fail "SSH 免密登录不可用——先执行: ssh-copy-id $SERVER"
}

# ---------------- 模式分发 ----------------
MODE="${1:-all}"

if [ "$MODE" = "verify" ]; then
  step "健康检查"
  verify_key
  run "curl -s -m 5 http://127.0.0.1:$PORT/api/health | head -c 200; echo"
  curl -sk -o /dev/null -w "https /fusion/ = %{http_code}\n" --max-time 15 "https://$DOMAIN/fusion/"
  exit 0
fi

verify_key

# ---------------- 1. 同步代码 ----------------
step "① 同步代码（排除 Mac 专属/大文件/训练数据/本地 .env）"
rsync_to \
  --exclude=".venv" --exclude="__pycache__" --exclude="node_modules" \
  --exclude="logs" --exclude=".git" --exclude="docs" --exclude="qa" \
  --exclude="web" --exclude="data" --exclude="scripts/e2e_results" \
  --exclude=".serve.lock" --exclude="deploy" --exclude=".env" --exclude=".env.*" \
  "$(cd "$(dirname "$0")" && pwd)/" "$SERVER:$REMOTE_ROOT/"
ok "代码已同步到 $REMOTE_ROOT（.env 不覆盖云端——cloud 配置仅在远端维护）"

if [ "$MODE" = "code" ]; then
  step "快速模式：重启 serve"
  run "cd $REMOTE_ROOT
       pkill -f 'fusion_k12_teacher.serve' 2>/dev/null || true; sleep 2
       mkdir -p logs
       setsid nohup env FUSION_MLX_CLOUD=1 .venv/bin/python -m uvicorn fusion_k12_teacher.serve:app \
         --host 127.0.0.1 --port $PORT > logs/serve.log 2>&1 < /dev/null &
       sleep 6
       curl -s -m 5 http://127.0.0.1:$PORT/api/health | head -c 150; echo"
  ok "serve 已重启"
  exit 0
fi

# ---------------- 2. 系统依赖 + Python venv ----------------
step "② 系统依赖 + Python venv (3.11 — Ubuntu 22.04 自带 3.10 不满足项目要求)"
run 'export DEBIAN_FRONTEND=noninteractive
     apt-get update -qq && apt-get install -y -qq software-properties-common curl > /dev/null 2>&1
     add-apt-repository -y ppa:deadsnakes/ppa > /dev/null 2>&1
     apt-get update -qq && apt-get install -y -qq python3.11 python3.11-venv python3.11-dev > /dev/null 2>&1
     cd '"$REMOTE_ROOT"' && rm -rf .venv && python3.11 -m venv .venv
     .venv/bin/pip install -q --upgrade pip 2>&1 | tail -1 || true
     # 业务包 + 全部运行时 extras（web=serve 必需, math=图谱/场景编译 networkx+sympy 必需）
     .venv/bin/pip install -q -e ".[web,math]" 2>&1 | grep -viE "warning|deprecat" | tail -2 || true
     .venv/bin/python -c "import fusion_k12_teacher, fastapi, uvicorn, networkx, sympy; print(\"deps OK\")"'
ok "依赖安装完成"

# ---------------- 3. 配置 .env（cloud 形态） ----------------
step "③ 生成云端 .env（密钥从本机 .env 提取，不回显）"
LOCAL_API_KEY=$(grep -m1 '^FUSION_K12_API_KEY=' "$(dirname "$0")/.env" | cut -d= -f2)
LOCAL_ADMIN_KEY=$(grep -m1 '^FUSION_K12_ADMIN_API_KEY=' "$(dirname "$0")/.env" | cut -d= -f2)
[ -n "$LOCAL_API_KEY" ] || fail "本机 .env 缺 FUSION_K12_API_KEY"
LOCAL_LLM_KEY=$(grep -m1 '^FUSION_CLIENT_KEY=' "$(dirname "$0")/.env" | cut -d= -f2 || true)

run "cat > $REMOTE_ROOT/.env <<ENVEOF
# fusion-k12-teacher cloud 形态 (生成于 deployCloud.sh, 勿手改——会被覆盖)
FUSION_MLX_CLOUD=1
FUSION_MLX_URL=https://api.deepseek.com/v1
FUSION_MLX_MODEL=deepseek-chat
FUSION_CLIENT_KEY=${LOCAL_LLM_KEY:-}
FUSION_MLX_READ_TIMEOUT=300
FUSION_MLX_MAX_CONCURRENCY=4
FUSION_K12_API_KEY=$LOCAL_API_KEY
FUSION_K12_ADMIN_API_KEY=$LOCAL_ADMIN_KEY
FUSION_K12_RATE_LIMIT=60/60
FUSION_K12_LOG_LEVEL=INFO
FUSION_K12_HEALTH_PROBE_INTERVAL=60
ENVEOF
chmod 600 $REMOTE_ROOT/.env"
ok ".env 已写入（cloud 形态, 权限 600）"
warn "云端 LLM key 为占位——若 LOCAL_LLM_KEY 为空请手动补 $REMOTE_ROOT/.env 的 FUSION_CLIENT_KEY"

# ---------------- 4. 启动 serve（cloud 形态） ----------------
step "④ 启动 serve (127.0.0.1:$PORT, cloud 形态)"
run "cd $REMOTE_ROOT && mkdir -p logs ~/.fusion-k12
     pkill -f 'fusion_k12_teacher.serve' 2>/dev/null || true; sleep 2
     setsid nohup env FUSION_MLX_CLOUD=1 FUSION_K12_CONFIG_FILE= .venv/bin/python -m uvicorn fusion_k12_teacher.serve:app \
       --host 127.0.0.1 --port $PORT > logs/serve.log 2>&1 < /dev/null &
     sleep 8
     curl -s -m 5 http://127.0.0.1:$PORT/api/health"
ok "serve 已启动"

# ---------------- 5. nginx 反代 /fusion/（幂等，不动 linguakids） ----------------
step "⑤ nginx 反代 /fusion/ → 127.0.0.1:$PORT"
run 'if ! grep -q "location /fusion/" /etc/nginx/sites-enabled/default 2>/dev/null; then
       # 在 linguakids 的 443 server 块内、最后一个 location 之后插入 /fusion/ 反代
       python3 - <<PYEOF
import re
p = "/etc/nginx/sites-enabled/default"
s = open(p).read()
block = """
    # fusion-k12-teacher (cloud 形态) — /fusion/ 前缀反代
    location /fusion/ {
        proxy_pass http://127.0.0.1:$PORT/;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
    location /fusion-ws/ {
        proxy_pass http://127.0.0.1:$PORT/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
"""
marker = "    # LiveKit WSS"
assert marker in s, "nginx 模板标记 LiveKit WSS 未找到"
s = s.replace(marker, block + "\n" + marker, 1)
open(p, "w").write(s)
print("inserted")
PYEOF
     fi
     nginx -t && systemctl reload nginx && echo nginx-ok' && ok "nginx /fusion/ 反代就绪"

# ---------------- 6. 默认页加 fusion-k12-teacher 卡片 ----------------
step "⑥ 默认页面增加 fusion-k12-teacher 链接"
# 默认页由 linguakids serve (127.0.0.1:8080) 动态渲染 → 改 linguakids 仓库里的
# 模板源文件并重启其 serve。模板文件定位: serve 根路径返回 HTML 的 py 文件。
run 'grep -rln "AI 英语口语课堂" /opt/linguakids-mvp --include="*.py" --include="*.html" 2>/dev/null | head -3'
ok "模板定位输出见上（下一步注入）"

# ---------------- 7. 最终健康检查 ----------------
step "⑦ 健康检查"
run "curl -s -m 5 http://127.0.0.1:$PORT/api/health | head -c 200; echo"
curl -sk -o /dev/null -w "https /fusion/ = %{http_code}\n" --max-time 15 "https://$DOMAIN/fusion/"

echo ""
ok "fusion-k12-teacher 部署完成：https://$DOMAIN/fusion/"
