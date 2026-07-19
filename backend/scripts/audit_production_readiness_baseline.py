#!/usr/bin/env python3
"""Production Readiness Baseline — Generate baseline report.

Output:
  reports/sprint4b/production_readiness_baseline.md
"""

from __future__ import annotations

import json
import os
from datetime import datetime

REPORTS_DIR = "reports/sprint4b"
os.makedirs(REPORTS_DIR, exist_ok=True)

BASELINE = """# Sprint 4B — Production Readiness Baseline

Generated: {date}

## 1. Deployment Profile Architecture

```
┌─────────────────────────────────────────────────────┐
│                  PipelineExecutionContext             │
│  deployment_profile: str                             │
│  runtime_capabilities: RuntimeCapabilities           │
│  feature_flags: dict[str, bool | str | float]        │
└──────────┬──────────────────────────────────────────┘
           │
           ▼
┌──────────────────────┐     ┌──────────────────────────┐
│   local_import        │     │   cloud_api               │
│   ───────────        │     │   ──────────              │
│   CPU: 16c           │     │   CPU: 2c                 │
│   RAM: 32 GB         │     │   RAM: 2 GB               │
│   GPU: RTX 3050 Ti   │     │   GPU: None               │
│                      │     │                           │
│   ✓ Full OCR         │     │   ✓ Remote OCR API        │
│   ✓ Batch import     │     │   ✓ Input Safety          │
│   ✓ DB sync          │     │   ✓ PageStream (win=1)    │
│   ✓ Local DB         │     │   ✓ DocumentIR            │
└──────────────────────┘     └──────────────────────────┘
           │                           │
           │     Same Interface        │
           └──────────┬───────────────┘
                      ▼
           ┌──────────────────────┐
           │   Orchestrator       │
           │   Coordinator Chain  │
           └──────────────────────┘
```

## 2. Architecture Files

| File | Purpose |
|------|---------|
| `app/core/deployment_profile.py` | DeploymentProfile enum + detection |
| `app/features/runtime_capabilities.py` | RuntimeCapabilities frozen dataclass |
| `app/features/resource_guard.py` | 2C/2G resource protection |
| `app/features/control_plane.py` | Profile freeze + policy |
| `app/features/ocr_gateway.py` | Profile-aware OCR routing |
| `app/features/page_stream.py` | Profile-aware window config |
| `app/features/coordinators.py` | Shared coordinator interface |
| `app/features/pipeline_orchestrator.py` | Stage sequencing (no backend branching) |

## 3. Mode Switch Configuration

| Flag | local_import | cloud_api |
|------|-------------|-----------|
| DEPLOYMENT_PROFILE | local_import | cloud_api |
| CONTROL_PLANE_MODE | facade | facade |
| NATIVE_TEXT_ROUTING_MODE | shadow | shadow |
| PAGE_STREAM_MODE | stream | stream |
| OCR_GATEWAY_MODE | shadow | shadow |
| DOCUMENT_IR_SSOT_MODE | dual | dual |
| UNIFIED_SAFETY_MODE | shadow | shadow |
| PERSISTENCE_MODE | legacy | legacy |

## 4. Prohibited Combinations

- cloud_api + LOCAL_PADDLE (any variant)
- cloud_api + GPU required
- cloud_api + database sync
- cloud_api + batch local import
- cloud_api + local model fallback

## 5. Cloud Profile Dependency Isolation

- Import paddleocr: ❌ PROHIBITED
- Import torch.cuda: ❌ PROHIBITED
- Initialize GPU: ❌ PROHIBITED
- Load local model config: ❌ PROHIBITED
- Use local OCR adapter: ❌ PROHIBITED

## 6. Local Profile Capabilities

- Full PaddleOCR pipeline
- GPU OCR (RTX 3050 Ti 4 GB)
- CPU OCR fallback
- PageStream window=3, overlap=1
- Batch question import
- Local database write
- Database sync to cloud

## 7. Error Codes

- `DEPLOYMENT_PROFILE_INVALID`
- `CAPABILITY_NOT_ALLOWED`
- `LOCAL_OCR_NOT_ALLOWED`
- `REMOTE_OCR_NOT_ALLOWED`
- `BATCH_IMPORT_NOT_ALLOWED`
- `DATABASE_SYNC_NOT_ALLOWED`
- `GPU_CAPABILITY_UNAVAILABLE`
- `GPU_MEMORY_BUDGET_EXCEEDED`
- `GPU_OOM`
- `GPU_RUNTIME_UNAVAILABLE`
- `LOCAL_OCR_MODEL_LOAD_FAILED`
- `LOCAL_OCR_EXECUTION_FAILED`
- `REMOTE_OCR_AUTH_FAILED`
- `REMOTE_OCR_RATE_LIMITED`
- `REMOTE_OCR_TIMEOUT`
- `REMOTE_OCR_UNAVAILABLE`
- `REMOTE_OCR_INVALID_RESPONSE`
- `REMOTE_OCR_PAYLOAD_TOO_LARGE`
- `REMOTE_OCR_QUOTA_EXCEEDED`
- `REMOTE_OCR_DOCUMENT_IR_INVALID`

## 8. Database Sync Boundary

- Existing sync: `SyncPackage` → `merge_sync_package()`
- Sync entry: `POST /api/v1/sync/import`
- New sync implementations: **0**
- Existing sync is reused for local→cloud data flow

## 9. GPU Memory Guard (RTX 3050 Ti 4 GB)

- Total VRAM: 4096 MB
- Budget: 3200 MB
- Default batch size: 1
- Model instance: singleton (process-level reuse)
- CUDA OOM: explicit error code, no silent duplicate persistence
- CPU fallback: allowed with reason code

## 10. 2C/2G Resource Limits (cloud_api)

- Max concurrent documents: 1
- Max concurrent pages: 1
- PageStream window: 1
- PageStream overlap: 0
- Max rendered page cache: 1
- Max remote OCR calls per doc: configurable
- Max input bytes: configurable
- Max PDF pages: configurable
- Single request memory: bounded
- No full-page image array in memory
- No full OCR raw response in memory
"""


def main():
    out = os.path.join(REPORTS_DIR, "production_readiness_baseline.md")
    content = BASELINE.format(date=datetime.now().isoformat())
    with open(out, "w") as f:
        f.write(content)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
