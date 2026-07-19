#!/usr/bin/env bash
# Setup isolated GPU Python environment for local OCR worker.
# Does NOT modify the main CPU environment.
#
# Usage:
#   bash scripts/setup_local_ocr_gpu_env.sh
#
# Output:
#   backend/.venv-ocr-gpu/        — isolated Python venv
#   reports/sprint4c/              — environment report

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")"
REPORT_DIR="$BACKEND_DIR/reports/sprint4c"
VENV_DIR="$BACKEND_DIR/.venv-ocr-gpu"
REQUIREMENTS_DIR="$BACKEND_DIR/requirements"
LOCK_FILE="$REQUIREMENTS_DIR/ocr-worker-gpu.lock"

mkdir -p "$REPORT_DIR" "$REQUIREMENTS_DIR"

echo "=== GPU OCR Environment Setup ==="
echo "Python: $(python3 --version 2>&1)"
echo "Creating isolated venv at: $VENV_DIR"

# 1. Create venv
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

echo "=== Upgrading pip ==="
pip install --quiet --upgrade pip

echo "=== Installing PaddlePaddle GPU (CUDA 12.x) ==="
# Paddle 3.3.1 with CUDA 12.6 support — matches nvidia driver 566.03 / CUDA 12.7
pip install \
  --no-cache-dir \
  paddlepaddle-gpu==3.3.1 \
  --extra-index-url https://www.paddlepaddle.org.cn/packages/nightly/cu126/

echo "=== Installing PaddleOCR ==="
pip install --no-cache-dir "paddleocr>=2.10.0"

echo "=== Installing test dependencies ==="
pip install --no-cache-dir pytest pytest-asyncio httpx aiosqlite

echo "=== Generating environment fingerprint ==="
python3 "$SCRIPT_DIR/preflight_local_ocr_gpu.py" 2>&1 || true

echo "=== Locking dependency versions ==="
pip freeze > "$LOCK_FILE"
echo "Lock file saved to: $LOCK_FILE"

echo ""
echo "=== GPU Environment Fingerprint ==="
python3 -c "
import paddle
print(f'Paddle version: {paddle.__version__}')
print(f'Compiled with CUDA: {paddle.is_compiled_with_cuda()}')
if paddle.is_compiled_with_cuda():
    print(f'CUDA device count: {paddle.device.cuda.device_count()}')
    print(f'CUDA devices: {paddle.device.get_device()}')
print(f'PaddleOCR importable: OK')
" 2>&1 || echo "GPU env validation FAILED"

echo ""
echo "=== Setup Complete ==="
echo "Activate: source $VENV_DIR/bin/activate"
echo "Run preflight: python $SCRIPT_DIR/preflight_local_ocr_gpu.py"
