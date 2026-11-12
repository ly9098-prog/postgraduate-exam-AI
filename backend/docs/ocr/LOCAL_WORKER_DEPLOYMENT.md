# Local OCR Worker Deployment Guide (Legacy)

> Applies to: legacy internal pull-mode OCR worker, not the current local GPU execution path.
> Current local GPU architecture: WSL backend → `httpx` → Windows PaddleX GPU service. WSL has no usable CUDA runtime and its local OCR inference is CPU-only.
> Production only calls a lightweight external OCR HTTPS API.
> Last updated: 2026-11-12

## Architecture

```
Production Server                   Legacy Pull Worker (see deprecation notice)
┌──────────────────────┐            ┌──────────────────────────┐
│ FastAPI + PostgreSQL │  claim ◄── │     Worker Daemon        │
│                      │  ──► input │        │                 │
│   OCR Job Control    │  heartbeat │   Executor Process       │
│   Result Validation  │  ──► result│   (PaddleOCR subprocess) │
│   Post-OCR Pipeline  │            └──────────────────────────┘
└──────────────────────┘
```

The worker uses **pull mode**: it polls the production server's internal API, claims jobs atomically, executes its legacy local PaddleOCR subprocess, and uploads results. This is retained as historical compatibility documentation; it must not be used to configure the current WSL local-import GPU workflow.

## Prerequisites

| Item | Requirement | Check |
|------|-------------|-------|
| CPU / host memory | Legacy daemon host requirements | `free -h` |
| Windows side | PaddleX GPU service reachable from WSL | `curl http://<windows-host>:8080/health` |
| Python | 3.10 – 3.12 | `python3 --version` |
| Disk | 20GB+ free for workspace | `df -h /data` |
| Network | HTTPS to production server | `curl https://your-production-domain.example/health` |

## Installation

### 1. Prepare Python environment

```bash
cd /opt/22408-ai/backend
source .venv/bin/activate
PYTHONPATH=. python -c "import app.ocr_worker.daemon; print('daemon import ok')"
```

This legacy daemon runs from the backend runtime. Do not use a WSL GPU venv: WSL CUDA is not supported in the current local setup. GPU inference belongs to the Windows PaddleX service.

### 2. Verify OCR runtime

```bash
source .venv/bin/activate
PYTHONPATH=. python -c "import paddle; print('cuda devices:', paddle.device.cuda.device_count())"
```
Expected in WSL: `cuda devices: 0`. GPU must be provided by the Windows PaddleX service, not inside WSL.

### 3. Register worker credential

On the production server, generate a credential:
```bash
# Start Python REPL on server
cd /opt/22408-ai/backend
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
cd /opt/22408-ai/backend
source .venv/bin/activate

# Export env vars
export OCR_WORKER_SERVER_URL=https://your-production-domain.example
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
