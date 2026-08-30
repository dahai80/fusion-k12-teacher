# fusion-k12-teacher 容器镜像 — v2.0 集群形态
# 多阶段: builder 装依赖, runtime 精简。Python 3.12-slim (Apple Silicon 本地可用, 集群 x86 需 cross-build)。
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

# 先装公共底座 + 本工程 (含 cluster 可选依赖) — 利用 layer 缓存
COPY fusion-k12-teacher /build/fusion-k12-teacher
RUN pip install --user /build/fusion-k12-teacher"[cluster,test]"

# runtime
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/root/.local/bin:${PATH}"

WORKDIR /app

# 复制安装产物 (site-packages + console scripts)
COPY --from=builder /root/.local /root/.local

# 非根用户运行 (最小权限)
RUN useradd -m -u 1001 k12 && chown -R k12:k12 /app
USER k12

EXPOSE 11448

# 健康检查用 serve 内置 /api/health (liveness) — 无需 API key
HEALTHCHECK --interval=15s --timeout=3s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:11448/api/health',timeout=2).status==200 else 1)"

# 默认启动 serve (cluster 模式由 FUSION_K12_MODE 控制)
ENTRYPOINT ["fusion-k12"]
CMD ["serve"]
