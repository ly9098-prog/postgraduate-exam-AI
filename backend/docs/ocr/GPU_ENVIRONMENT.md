# GPU Environment Setup — Local OCR Worker

> Last updated: 2026-07-17

## Prerequisites

| Item | Requirement |
|------|-------------|
| NVIDIA GPU | 4 GB+ VRAM recommended |
| NVIDIA Driver | >= 535 (supports CUDA 12.x) |
| Python | 3.10 – 3.12 |
| CUDA Runtime | Provided by driver (nvcc not required) |

## Environment

The GPU OCR worker runs in an **isolated** virtual environment separate from the main CPU environment:

- **Path**: `backend/.venv-ocr-gpu/`
- **Activation**: `source .venv-ocr-gpu/bin/activate`
- **Lockfile**: `backend/requirements/ocr-worker-gpu.lock`

### Why isolation?

- Main environment uses CPU-only `paddlepaddle==3.3.1`
- GPU environment uses `paddlepaddle-gpu==3.3.1` (compiled with CUDA)
- Prevents dependency conflicts
- Allows independent upgrade/rollback of GPU packages

## Quick Start

```bash
cd backend
bash scripts/setup_local_ocr_gpu_env.sh
```

This will:
1. Create `.venv-ocr-gpu/`
2. Install `paddlepaddle-gpu==3.3.1` from Paddle cu126 source
3. Install `paddleocr>=2.10.0`
4. Run preflight checks
5. Generate `reports/sprint4c/gpu_environment.json`

## Verification

```bash
source .venv-ocr-gpu/bin/activate
PYTHONPATH=. python scripts/preflight_local_ocr_gpu.py
```

## GPU Smoke Test

```bash
OCR_LIVE_GPU_TEST=1 \
  .venv-ocr-gpu/bin/python -m pytest tests/test_live_local_adapter_smoke.py -v
```

## Known Issues

1. **cu126 vs local CUDA version mismatch**: Paddle cu126 wheels are compatible with
   driver CUDA 12.7+. If the local CUDA driver is older, install a compatible wheel.
2. **First model download**: PaddleOCR downloads model weights on first use (~200 MB).
   Ensure network access to Baidu/Paddle servers.
3. **GPU memory fragmentation**: After heavy usage, GPU memory may appear unfreed.
   Use `nvidia-smi` to verify and `paddle.device.cuda.empty_cache()` to release.
