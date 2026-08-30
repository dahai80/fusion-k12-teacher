FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY . .

RUN pip install --no-cache-dir -e ".[web]"

RUN useradd -m -u 1000 fusion && mkdir -p /home/fusion/.fusion-k12 /app/fusion_k12_teacher/data \
    && chown -R fusion:fusion /home/fusion /app
USER fusion

ENV FUSION_K12_HOME=/home/fusion/.fusion-k12 \
    FUSION_K12_HISTORY_FILE=/home/fusion/.fusion-k12/history.json \
    FUSION_K12_SCHEDULER_PIDFILE=/home/fusion/.fusion-k12/scheduler.pid \
    FUSION_K12_SCHEDULER_DB=/home/fusion/.fusion-k12/scheduler.db \
    FUSION_K12_INSTANCE_LOCK=/home/fusion/.fusion-k12/serve.lock \
    FUSION_K12_DATA_DIR=/app/fusion_k12_teacher/data

EXPOSE 11448

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:11448/api/health',timeout=5).status==200 else 1)"

CMD ["fusion-k12", "serve", "--host", "0.0.0.0", "--port", "11448"]
