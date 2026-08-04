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
| `FUSION_MLX_URL` | `http://fusion-mlx:11432` | fusion-mlx 后端地址 |
| `FUSION_K12_PORT` | `11448` | HTTP API 端口 |

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
        image: fusion-k12-teacher:1.0.2
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
# {"status": "ok", "version": "1.0.2"}
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
