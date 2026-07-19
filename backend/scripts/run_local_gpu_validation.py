#!/usr/bin/env python3
"""Run Local GPU Validation — Requires RTX 3050 Ti 4 GB with PaddleOCR.

Usage:
  DEPLOYMENT_PROFILE=local_import OCR_GATEWAY_MODE=gateway \\
  PYTHONPATH=. python scripts/run_local_gpu_validation.py

Output:
  reports/sprint4c/local_gpu_environment.json
  reports/sprint4c/local_gpu_benchmark.json
  reports/sprint4c/local_gpu_memory_profile.json
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime

REPORTS_DIR = "reports/sprint4c"
os.makedirs(REPORTS_DIR, exist_ok=True)


def check_gpu_available() -> bool:
    """Check if CUDA GPU is available."""
    try:
        import paddle
        if paddle.is_compiled_with_cuda():
            return True
        return False
    except ImportError:
        return False


def get_gpu_info() -> dict:
    """Get GPU information."""
    try:
        import paddle
        if not paddle.is_compiled_with_cuda():
            return {"available": False, "note": "Paddle not compiled with CUDA"}

        gpu_count = paddle.device.cuda.device_count()
        if gpu_count == 0:
            return {"available": False, "note": "CUDA available but device_count=0"}

        props = {}
        try:
            props["name"] = paddle.device.cuda.get_device_name(0)
            props["capability"] = paddle.device.cuda.get_device_capability(0)
            props["memory_total_mb"] = paddle.device.cuda.mem_info()[0] // (1024 * 1024) if hasattr(paddle.device.cuda, "mem_info") else None
        except Exception:
            pass

        return {
            "available": True,
            "count": gpu_count,
            "properties": props,
        }
    except Exception as e:
        return {"available": False, "error": str(e)}


def main():
    gpu_info = get_gpu_info()

    # Environment report
    env_report = {
        "timestamp": datetime.now().isoformat(),
        "deployment_profile": os.environ.get("DEPLOYMENT_PROFILE", "not_set"),
        "ocr_gateway_mode": os.environ.get("OCR_GATEWAY_MODE", "not_set"),
        "gpu": gpu_info,
    }

    if not gpu_info.get("available", False):
        env_report["status"] = "environment_not_available"
        env_report["note"] = "No CUDA GPU detected. Requires RTX 3050 Ti 4 GB."
        print("GPU not available — marking environment_not_available")
        print("To run this test:")
        print("  1. Ensure RTX 3050 Ti 4 GB is accessible")
        print("  2. Install PaddleOCR with CUDA support")
        print("  3. Set DEPLOYMENT_PROFILE=local_import")
        print("  4. Run: PYTHONPATH=. python scripts/run_local_gpu_validation.py")
    else:
        env_report["status"] = "environment_available"
        env_report["note"] = f"GPU: {gpu_info.get('properties', {}).get('name', 'unknown')}"

    out = os.path.join(REPORTS_DIR, "local_gpu_environment.json")
    with open(out, "w") as f:
        json.dump(env_report, f, indent=2, ensure_ascii=False)
    print(f"Wrote {out}")

    # Benchmark and memory profile (stubs for now)
    benchmark = {
        "timestamp": datetime.now().isoformat(),
        "gpu_available": gpu_info.get("available", False),
        "tests": [
            {"name": "single_page_ocr", "status": "not_run", "note": "Requires test document"},
            {"name": "10_page_document", "status": "not_run"},
            {"name": "100_page_document", "status": "not_run"},
            {"name": "mixed_resolution", "status": "not_run"},
            {"name": "high_pixel_page", "status": "not_run"},
            {"name": "consecutive_imports", "status": "not_run"},
            {"name": "artifact_resume", "status": "not_run"},
        ],
        "metrics_required": [
            "model_initialization_count",
            "duplicate_ocr_count",
            "default_batch_size",
            "peak_vram_mb",
            "page_image_memory_release",
            "cpu_fallback_reason_code",
            "document_ir_schema_after_fallback",
        ],
    }

    out = os.path.join(REPORTS_DIR, "local_gpu_benchmark.json")
    with open(out, "w") as f:
        json.dump(benchmark, f, indent=2, ensure_ascii=False)
    print(f"Wrote {out}")

    memory_profile = {
        "timestamp": datetime.now().isoformat(),
        "gpu_available": gpu_info.get("available", False),
        "note": "Requires GPU stress test harness",
    }

    out = os.path.join(REPORTS_DIR, "local_gpu_memory_profile.json")
    with open(out, "w") as f:
        json.dump(memory_profile, f, indent=2, ensure_ascii=False)
    print(f"Wrote {out}")

    print(f"\nGPU available: {gpu_info.get('available', False)}")
    print(f"See {REPORTS_DIR}/ for results")


if __name__ == "__main__":
    main()
