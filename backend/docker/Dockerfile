# Stage 1: Build dependencies
FROM python:3.11-slim AS builder

WORKDIR /app
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    PIPOPT="pip install --timeout=120 --retries=5 --user -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com" && \
    $PIPOPT -r requirements.txt
COPY requirements-ocr.txt .
# Install OCR deps + paddleocr without its opencv deps (replaced by headless)
RUN --mount=type=cache,target=/root/.cache/pip \
    PIPOPT="pip install --timeout=120 --retries=5 --user -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com" && \
    $PIPOPT -r requirements-ocr.txt && \
    $PIPOPT --no-deps paddleocr

# Stage 2: Runtime
FROM python:3.11-slim

RUN groupadd -r app && useradd -r -g app app

RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list 2>/dev/null; \
    sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null; \
    sed -i 's|http://|https://|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null; \
    apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    libglib2.0-0 \
    libgomp1 \
    fonts-wqy-zenhei \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /root/.local /home/app/.local
COPY --chown=app:app . .

ENV PATH=/home/app/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1
# matplotlib 缓存写入可写目录（app 用户无 /home/app/.config 写权限）
ENV MPLCONFIGDIR=/tmp/matplotlib

# Pre-create staging dir for durable task files (Docker volume mount point)
RUN mkdir -p /opt/2240ai-v2/staging && chown app:app /opt/2240ai-v2/staging && chmod 700 /opt/2240ai-v2/staging
# Pre-create export dir for local export file persistence
RUN mkdir -p /opt/2240ai-v2/exports && chown app:app /opt/2240ai-v2/exports && chmod 700 /opt/2240ai-v2/exports

USER app

EXPOSE 8000

# Use GUNICORN_WORKERS env var (default 2 for memory-constrained servers).
# Increase to 4 on servers with >=4GB RAM and >=4 CPU cores.
# With 4 PaddleOCR-capable workers + PaddlePaddle, each instance needs ~200-500MB.
CMD gunicorn app.main:app \
    -k uvicorn.workers.UvicornWorker \
    -w ${GUNICORN_WORKERS:-2} \
    --bind 0.0.0.0:8000 \
    --forwarded-allow-ips=* \
    --access-logfile - \
    --error-logfile -
