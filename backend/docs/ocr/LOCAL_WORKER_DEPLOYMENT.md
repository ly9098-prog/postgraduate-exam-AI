# Local OCR Worker Deployment Guide

> Applies to: Local GPU OCR Worker (RTX 3050 / CUDA 12.x)
> Server target: xzshub.top (2C/2G thin production server)
> Last updated: 2026-07-17

## Architecture

```
Production Server (2C/2G)           Local GPU Worker (i7 / RTX 3050 4G)
┌──────────────────────┐            ┌──────────────────────────┐
│ FastAPI + PostgreSQL │  claim ◄── │     Worker Daemon        │
│                      │  ──► input │        │                 │
│   OCR Job Control    │  heartbeat │   Executor Process       │
│   Result Validation  │  ──► result│   (PaddleOCR subprocess) │
│   Post-OCR Pipeline  │            └──────────────────────────┘
└──────────────────────┘
```

The worker uses **pull mode**: it polls the production server's internal API, claims jobs atomically, processes them locally with GPU-accelerated PaddleOCR, and uploads results.

## Prerequisites

| Item | Requirement | Check |
|------|-------------|-------|
| NVIDIA GPU | RTX 3050+ (4GB VRAM) | `nvidia-smi` |
| NVIDIA Driver | >= 535 (CUDA 12.x) | `nvidia-smi --query-gpu=driver_version` |
| Python | 3.10 – 3.12 | `python3 --version` |
| Disk | 20GB+ free for workspace | `df -h /data` |
| Network | HTTPS to production server | `curl https://xzshub.top/health` |

## Installation

### 1. Prepare Python environment

```bash
cd /opt/2240ai-v2/backend
source .venv/bin/activate
PYTHONPATH=. python -c "import paddleocr; print(paddleocr.__version__)"
```

Worker runs in CPU mode (`.venv` 使用 CPU paddlepaddle)。GPU OCR 环境已废弃删除（WSL2 dxgkrnl 限制）。

### 2. Verify OCR runtime

```bash
source .venv/bin/activate
PYTHONPATH=. python -c "import paddle; print('cpu devices:', paddle.device.cuda.device_count())"
```
Expected: OCR 走 CPU / remote paddlex backend。

### 3. Register worker credential

On the production server, generate a credential:
```bash
# Start Python REPL on server
cd /opt/2240ai-v2/backend
source .venv/bin/activate
PYTHONPATH=. python -c "
from app.services.worker_credential_service import create_credential, hash_key
import asyncio
from app.core.database import async_session

async def reg():
    async with async_session() as db:
        cred, key = await create_credential(db, 'local-ocr-01')
        print(f'Credential ID: {cred.id}')
        print(f'Raw API Key: {key}')
        print(f'Store this key in ocr-worker.env!')
asyncio.run(reg())
"
```

### 4. Configure worker

Copy and edit the env file:
```bash
cp deploy/ocr-worker/ocr-worker.env.example deploy/ocr-worker/ocr-worker.env
chmod 600 deploy/ocr-worker/ocr-worker.env
# Edit OCR_WORKER_API_KEY with the key from step 3
```

### 5. Install systemd service

```bash
sudo cp deploy/ocr-worker/ocr-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable ocr-worker
sudo systemctl start ocr-worker
```

## Quick Start (Manual)

```bash
cd /opt/2240ai-v2/backend
source .venv-ocr-gpu/bin/activate

# Export env vars
export OCR_WORKER_SERVER_URL=https://xzshub.top
export OCR_WORKER_ID=local-ocr-01
export OCR_WORKER_API_KEY=<generated-key>

# Run daemon
PYTHONPATH=. python -m app.ocr_worker.daemon --verbose
```

## Stage 1: Allowlist Testing

Before full rollout, test with explicit allowlist documents:

```bash
# Production side: set allowlist
export OCR_WORKER_DOCUMENT_ALLOWLIST='["doc-001","doc-002"]'

# Worker side: start with allowlist
export OCR_WORKER_ALLOWLIST_ONLY=true
PYTHONPATH=. python -m app.ocr_worker.daemon --verbose
```

Monitor with:
```bash
journalctl -u ocr-worker -f
```
