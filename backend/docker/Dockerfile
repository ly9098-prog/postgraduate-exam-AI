# Stage 1: Build dependencies
FROM python:3.11-slim AS builder

WORKDIR /app
COPY requirements.txt .
RUN PIPOPT="pip install --no-cache-dir --timeout=120 --retries=5 --user -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com" && \
    $PIPOPT -r requirements.txt
COPY requirements-ocr.txt .
# Install OCR deps + paddleocr without its opencv deps (replaced by headless)
RUN PIPOPT="pip install --no-cache-dir --timeout=120 --retries=5 --user -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com" && \
    $PIPOPT -r requirements-ocr.txt && \
    $PIPOPT --no-deps paddleocr

# Pre-download PaddleOCR models to ~/.paddleocr/ (PaddleOCR default model dir).
RUN python3 <<'PYEOF'
import os, tarfile, urllib.request
home = os.environ['HOME']
models = [
    ('https://paddleocr.bj.bcebos.com/PP-OCRv4/chinese/ch_PP-OCRv4_det_infer.tar', 'det/ch/ch_PP-OCRv4_det_infer'),
    ('https://paddleocr.bj.bcebos.com/PP-OCRv4/chinese/ch_PP-OCRv4_rec_infer.tar', 'rec/ch/ch_PP-OCRv4_rec_infer'),
    ('https://paddleocr.bj.bcebos.com/dygraph_v2.0/ch/ch_ppocr_mobile_v2.0_cls_infer.tar', 'cls/ch_ppocr_mobile_v2.0_cls_infer'),
]
base = os.path.join(home, '.paddleocr', 'whl')
os.makedirs(base, exist_ok=True)
for url, subdir in models:
    target = os.path.join(base, subdir)
    if os.path.exists(os.path.join(target, 'inference.pdmodel')):
        print(f'Skipping {subdir} (exists)')
        continue
    tar_name = url.split('/')[-1]
    os.makedirs(target, exist_ok=True)
    tar_path = os.path.join(target, tar_name)
    print(f'Downloading {tar_name}...')
    urllib.request.urlretrieve(url, tar_path)
    print(f'Extracting...')
    with tarfile.open(tar_path) as t:
        for member in t.getmembers():
            for suf in ('.pdiparams', '.pdiparams.info', '.pdmodel'):
                if member.name.endswith(suf):
                    member.name = 'inference' + suf
                    t.extract(member, target)
                    break
    os.remove(tar_path)
    print(f'Done: {subdir}')
print('All PaddleOCR models pre-downloaded')
PYEOF

# Stage 2: Runtime
FROM python:3.11-slim

RUN groupadd -r app && useradd -r -g app app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    fonts-wqy-zenhei \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /root/.local /home/app/.local
COPY --from=builder --chown=app:app /root/.paddleocr /home/app/.paddleocr
COPY --chown=app:app . .

ENV PATH=/home/app/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1

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
