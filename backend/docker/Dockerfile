# Stage 1: Build dependencies
FROM python:3.11-slim AS builder

WORKDIR /app
# requirements.lock is resolved for Python 3.11 / linux from requirements.txt
# (uv pip compile requirements.txt --python-version 3.11 --python-platform linux
#  --generate-hashes -o requirements.lock); pip refuses any file whose hash differs.
COPY requirements.txt requirements.lock ./
RUN --mount=type=cache,target=/root/.cache/pip \
    PIPOPT="pip install --timeout=120 --retries=5 --user -i https://mirrors.aliyun.com/pypi/simple/" && \
    $PIPOPT --require-hashes --no-deps -r requirements.lock

# Local development keeps the optional OCR runtime available by default. Cloud
# production sets INSTALL_OCR=false because OCR is provided by the remote API.
ARG INSTALL_OCR=true
COPY requirements-ocr.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    if [ "$INSTALL_OCR" = "true" ]; then \
      PIPOPT="pip install --timeout=120 --retries=5 --user -i https://mirrors.aliyun.com/pypi/simple/" && \
      $PIPOPT -r requirements-ocr.txt && \
      $PIPOPT --no-deps paddleocr; \
    else \
      echo "Skipping optional OCR dependencies (INSTALL_OCR=$INSTALL_OCR)"; \
    fi

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
RUN mkdir -p /app/staging && chown app:app /app/staging && chmod 700 /app/staging
# Pre-create export dir for local export file persistence
RUN mkdir -p /app/exports && chown app:app /app/exports && chmod 700 /app/exports
# fontconfig 缓存目录（app 无写权限 → "No writable cache directories"，字体仍可用但无缓存）
RUN mkdir -p /home/app/.cache && chown app:app /home/app/.cache
# 用户头像上传持久化（Docker volume mount point；static/ 被 gitignore，镜像内显式预建保证命名卷首挂继承 app 属主）
RUN mkdir -p /app/static/avatars && chown app:app /app/static/avatars && chmod 755 /app/static/avatars

USER app

EXPOSE 8000

# Use GUNICORN_WORKERS env var. Production defaults to 4 in compose because
# local PaddleOCR is not installed in the production image; tune with the DB
# connection-pool budget in mind.
CMD gunicorn app.main:app \
    -k uvicorn.workers.UvicornWorker \
    -w ${GUNICORN_WORKERS:-4} \
    --bind 0.0.0.0:8000 \
    --forwarded-allow-ips=* \
    --access-logfile - \
    --error-logfile -
