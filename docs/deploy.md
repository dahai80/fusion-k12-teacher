# Fusion-K12-Teacher 部署指南

## 场景一：个人教师本地使用

无需备案，零配置启动。

```bash
# 安装
git clone https://github.com/dahai80/fusion-k12-teacher.git
cd fusion-k12-teacher
pip install -e .

# 启动 fusion-mlx 后端
~/claude-home/fusion-mlx/start.sh start

# CLI 使用
fusion-k12 lesson plan 数学 3 分数

# 或启动 HTTP API
fusion-k12 serve --port 11448
```

访问 API 文档：http://localhost:11448/docs

## 场景二：学校内网部署

校内非商用，无需算法备案。使用 Docker 部署。

### 前置条件

- macOS Apple Silicon 服务器（M1/M2/M3/M4）
- Docker Desktop 或 Docker Engine
- fusion-mlx 镜像

### 部署步骤

```bash
# 1. 构建 fusion-k12-teacher 镜像
cd fusion-k12-teacher
docker build -t fusion-k12-teacher:latest .

# 2. 启动服务
docker-compose up -d

# 3. 验证
curl http://localhost:11448/api/health
```

### 配置说明

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `FUSION_MLX_URL` | `http://localhost:11432/v1` | fusion-gateway/MLX 后端地址 (gateway:11432, mlx 本体:11434) |
| `FUSION_MLX_MODEL` | (自动选择) | 指定模型 ID, 留空则 `_auto_select_model` 跳过非聊天模型 |
| `FUSION_MLX_API_KEY` | (空) | gateway/MLX 鉴权 key (401/403 触发 NonDegradableError) |
| `FUSION_MLX_CONNECT_TIMEOUT` | `10` | 连接超时秒 |
| `FUSION_MLX_READ_TIMEOUT` | `120` | 推理读超时秒 |
| `FUSION_MLX_MAX_RETRIES` | `2` | 瞬态错误重试次数 |
| `FUSION_MLX_MAX_CONCURRENCY` | `4` | 全局 LLM 并发信号量 (防本地单卡 OOM) |
| `FUSION_MLX_MODELS_TTL` | `30` | 模型列表缓存秒 |
| `FUSION_K12_PORT` | `11448` | HTTP API 端口 (serve 命令读取) |
| `FUSION_K12_API_KEY` | (空) | API 鉴权 key (客户端 X-API-Key 头); 空则仅回环免鉴权 |
| `FUSION_K12_ADMIN_API_KEY` | (空) | 管理 key (词表增删等敏感操作) |
| `FUSION_K12_RATE_LIMIT` | `60` | 每客户端每分钟请求上限 |
| `FUSION_K12_RATE_WINDOW` | `60` | 限流滑动窗口秒 |
| `FUSION_K12_RATE_STATE_FILE` | (空) | 跨进程共享限流状态文件 (多 worker) |
| `FUSION_K12_HOME` | `~/.fusion-k12` | 数据根目录 |
| `FUSION_K12_HISTORY_FILE` | `$HOME/history.json` | agent 任务历史持久化 |
| `FUSION_K12_SCHEDULER_DB` | (空→Memory) | scheduler SQLite 持久化路径 (配置即启用 SQLAlchemyJobStore) |
| `FUSION_K12_SCHEDULER_PIDFILE` | `$HOME/scheduler.pid` | cron 跨进程互斥 pidfile |
| `FUSION_K12_INSTANCE_LOCK` | `$HOME/serve.lock` | serve 单实例锁 |
| `FUSION_K12_DATA_DIR` | `包内 data/` | 课标/敏感词等数据目录 |
| `FUSION_K12_SALT` / `FUSION_K12_SALT_FILE` | (随机回退) | 脱敏 salt (多节点须统一分发) |
| `FUSION_K12_NAME_MAP_FILE` | (空→不落盘) | 反匿名表持久化路径 |
| `FUSION_K12_LIVE_TESTS` | `0` | 测试用: 1 启用真实 LLM 用例 |
| `FUSION_K12_CRON_RETRIES` | `1` | cron 任务失败重试次数 |
| `LOG_LEVEL` / `FUSION_K12_LOG_LEVEL` | `INFO` | 日志级别 |

完整可配置项见根目录 `.env.example`。

### 数据持久化

```bash
# 学生数据目录挂载
docker run -v /path/to/data:/app/data fusion-k12-teacher:latest
```

## 场景三：教培机构商用部署

需完成网信办算法备案，使用境内服务器。

### 合规要求

1. **算法备案**：在网信办完成"生成式人工智能服务备案"
2. **数据存储**：使用境内服务器，数据不出境
3. **内容安全**：启用完整安全过滤（safety 模块）
4. **数据脱敏**：对导出数据自动脱敏（desensitize 模块）
5. **访问控制**：配置认证中间件

### K8s 部署示例

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: fusion-k12-teacher
spec:
  replicas: 2
  selector:
    matchLabels:
      app: fusion-k12-teacher
  template:
    spec:
      containers:
      - name: fusion-k12
        image: fusion-k12-teacher:2.0.0a0
        ports:
        - containerPort: 11448
        env:
        - name: FUSION_MLX_URL
          value: "http://fusion-mlx-service:11432"
        resources:
          requests:
            memory: "2Gi"
          limits:
            memory: "4Gi"
---
apiVersion: v1
kind: Service
metadata:
  name: fusion-k12-service
spec:
  selector:
    app: fusion-k12-teacher
  ports:
  - port: 11448
    targetPort: 11448
```

### 安全配置

```bash
# 启用严格安全模式
fusion-k12 safety check --grade 3 "待检查内容"

# 数据导出前脱敏
fusion-k12 desensitize export data.json --output desensitized.json

# 敏感词库管理
fusion-k12 safety wordlist --add "新敏感词"
```

## 健康检查

```bash
# HTTP API 健康检查
curl http://localhost:11448/api/health

# 预期返回
# {"status": "ok", "version": "2.0.0a0"}
```

## 常见问题

### Q: fusion-mlx 连接失败

确保 fusion-mlx 服务已启动：
```bash
~/claude-home/fusion-mlx/start.sh start
curl http://localhost:11432/v1/models
```

### Q: 模型未下载

通过镜像站下载：
```bash
export HF_ENDPOINT=https://hf-mirror.com
huggingface-cli download Qwen/Qwen3.5-9B
```

### Q: Docker 内无法访问 fusion-mlx

检查 `docker-compose.yml` 中 `FUSION_MLX_URL` 配置，确保指向正确的服务名。

## 运维手册 (Runbook)

### 轮换 API Key

1. 生成新 key: `python -c "import secrets;print(secrets.token_hex(24))"`
2. 更新 `FUSION_K12_API_KEY` (compose env 或 K8s Secret)
3. 重启服务: `docker-compose restart fusion-k12` / `kubectl rollout restart deploy/fusion-k12`
4. 同步更新所有客户端的 `X-API-Key` 头

### 重启服务

```bash
# Docker
docker-compose restart fusion-k12
# 单机 CLI
~/claude-home/fusion-mlx/start.sh stop
fusion-k12 serve  # 单实例锁防重复启动
```

### 更换推理模型

1. 下载模型: `HF_ENDPOINT=https://hf-mirror.com huggingface-cli download <model>`
2. 启动/确认 fusion-mlx 已加载: `~/claude-home/fusion-mlx/start.sh status`
3. 设 `FUSION_MLX_MODEL=<model-id>` 或留空自动选择, 重启 k12 服务

### 恢复备份

- **数据卷** (`k12-data`): history.json / scheduler.db / salt / 上传数据 — `docker volume` 定期快照
- **反匿名表** (`FUSION_K12_NAME_MAP_FILE`): 与脱敏数据生命周期绑定, 单独加密存储, 勿与脱敏数据同处
- **salt** (`FUSION_K12_SALT_FILE`): 多节点须共享同一 salt, 否则同一学生跨节点 ID 断链; 备份后务必分发到所有节点
- 恢复: 挂回对应卷/文件后重启服务即可; scheduler.db 恢复后 cron 调度自动续接
