#!/usr/bin/env python3
"""Pre-flight check for local GPU OCR environment.

Generates:
  reports/sprint4c/gpu_environment.json  — structured env report
  reports/sprint4c/gpu_environment.md    — human-readable summary

Usage:
    source .venv-ocr-gpu/bin/activate
    PYTHONPATH=. python scripts/preflight_local_ocr_gpu.py

Exit code:
    0 — all checks passed
    1 — one or more checks failed (details in report)
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


REPORT_DIR = Path("reports/sprint4c")
REPORT_DIR.mkdir(parents=True, exist_ok=True)

# Also write Sprint 4D report
REPORT_DIR_4D = Path("reports/sprint4d")
REPORT_DIR_4D.mkdir(parents=True, exist_ok=True)


def run() -> int:
    checks: dict[str, Any] = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "system": _get_system_info(),
        "wsl2": _get_wsl2_info(),
        "compatibility": _get_compatibility_info(),
        "gpu_hardware": _get_gpu_hardware_info(),
        "paddle": {},
        "paddleocr": {},
        "tests": {},
    }

    passed = 0
    failed = 0

    # ── Paddle import ──
    try:
        import paddle
        checks["paddle"]["version"] = paddle.__version__
        checks["paddle"]["imported"] = True
        passed += 1
    except ImportError as e:
        checks["paddle"]["imported"] = False
        checks["paddle"]["error"] = str(e)
        failed += 1

    if checks["paddle"].get("imported"):
        # is_compiled_with_cuda
        cuda_ok = paddle.is_compiled_with_cuda()
        checks["paddle"]["compiled_with_cuda"] = cuda_ok
        if cuda_ok:
            passed += 1
        else:
            checks["paddle"]["_fail"] = "paddle.is_compiled_with_cuda() returned False"
            failed += 1

        # device count
        if cuda_ok:
            dev_count = paddle.device.cuda.device_count()
            checks["paddle"]["cuda_device_count"] = dev_count
            if dev_count >= 1:
                passed += 1
            else:
                checks["paddle"]["_fail"] = f"cuda.device_count() = {dev_count}, expected >= 1"
                failed += 1

            # device name
            try:
                dev_name = paddle.device.cuda.get_device_name()
                checks["paddle"]["cuda_device_name"] = dev_name
            except Exception as e:
                checks["paddle"]["cuda_device_name"] = f"error: {e}"
                failed += 1

            # run_check
            try:
                paddle.utils.run_check()
                checks["paddle"]["run_check"] = "passed"
                passed += 1
            except Exception as e:
                checks["paddle"]["run_check"] = f"failed: {e}"
                failed += 1

            # small tensor test
            try:
                start = time.monotonic()
                x = paddle.randn([1000, 1000])
                y = paddle.matmul(x, x.T)
                _ = y.numpy()
                elapsed = (time.monotonic() - start) * 1000
                checks["paddle"]["tensor_test_ms"] = round(elapsed, 2)
                passed += 1
            except Exception as e:
                checks["paddle"]["tensor_test"] = f"error: {e}"
                failed += 1

    # ── PaddleOCR import ──
    try:
        from paddleocr import PaddleOCR
        checks["paddleocr"]["imported"] = True
        checks["paddleocr"]["version"] = (
            PaddleOCR.__version__ if hasattr(PaddleOCR, "__version__") else "unknown"
        )
        passed += 1
    except ImportError as e:
        checks["paddleocr"]["imported"] = False
        checks["paddleocr"]["error"] = str(e)
        failed += 1

    # ── Summary ──
    checks["summary"] = {
        "passed": passed,
        "failed": failed,
        "status": "passed" if failed == 0 else "failed",
    }

    # Write JSON reports
    for rd in [REPORT_DIR, REPORT_DIR_4D]:
        json_path = rd / "gpu_compatibility_probe.json"
        json_path.write_text(json.dumps(checks, indent=2, ensure_ascii=False))
        print(f"Report: {json_path}")
        md = _format_markdown(checks)
        md_path = rd / "gpu_compatibility_probe.md"
        md_path.write_text(md)
        print(f"Report: {md_path}")

    print(f"\nChecks: {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


def _get_system_info() -> dict[str, Any]:
    info: dict[str, Any] = {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
    }
    # Check ldconfig for CUDA libs
    try:
        result = subprocess.run(
            ["ldconfig", "-p"], capture_output=True, text=True, timeout=5
        )
        cuda_libs = [l for l in result.stdout.split("\n") if "cuda" in l.lower()]
        info["cuda_libs_found"] = len(cuda_libs)
        info["cuda_libs"] = [l.strip().split(" ")[0] for l in cuda_libs[:10]]
    except Exception:
        info["cuda_libs_found"] = 0
    return info


def _get_wsl2_info() -> dict[str, Any]:
    """Detect WSL2 environment details."""
    info: dict[str, Any] = {
        "is_wsl2": False,
    }
    # Check for WSL2
    try:
        with open("/proc/version", "r") as f:
            version = f.read()
            info["is_wsl2"] = "microsoft" in version.lower() or "wsl" in version.lower()
    except Exception:
        pass
    # Kernel info
    try:
        result = subprocess.run(["uname", "-r"], capture_output=True, text=True, timeout=5)
        info["kernel"] = result.stdout.strip()
    except Exception:
        info["kernel"] = ""
    # WSL memory
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    info["total_memory_mb"] = kb // 1024
                elif line.startswith("MemAvailable:"):
                    kb = int(line.split()[1])
                    info["available_memory_mb"] = kb // 1024
                elif line.startswith("SwapTotal:"):
                    kb = int(line.split()[1])
                    info["swap_total_mb"] = kb // 1024
    except Exception:
        pass
    return info


def _get_compatibility_info() -> dict[str, Any]:
    """Check compatibility for Paddle GPU wheel installation."""
    info: dict[str, Any] = {}

    # Python ABI
    info["python_version"] = platform.python_version()
    info["python_abi"] = f"cp{sys.version_info.major}{sys.version_info.minor}"
    info["architecture"] = platform.machine()
    info["platform_tag"] = f"manylinux_{_get_glibc_version()}_x86_64"

    # glibc version
    glibc = _get_glibc_version()
    info["glibc_version"] = glibc

    # pip version
    info["pip_version"] = __import__("pip").__version__

    # Disk
    import shutil
    total, used, free = shutil.disk_usage("/")
    info["disk_free_gb"] = free // (1024**3)
    info["disk_total_gb"] = total // (1024**3)

    # CPU info
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("model name"):
                    info["cpu_model"] = line.split(":", 1)[1].strip()
                    break
    except Exception:
        info["cpu_model"] = ""
    # CPU count
    info["cpu_count"] = os.cpu_count() or 0

    # Check if CUDA 12.x is expected to work
    nvcc_info = _get_nvcc_info() or {}
    info["nvcc_cuda_version"] = nvcc_info.get("cuda_version", "")
    nvsmi = _get_gpu_hardware_info()
    info["nvidia_driver_version"] = nvsmi.get("driver_version", "")
    info["nvidia_cuda_version"] = nvsmi.get("cuda_version_str", "")

    # CPU Paddle env path
    venv = os.environ.get("VIRTUAL_ENV", "")
    info["current_venv"] = venv
    info["cpu_env_path"] = ".venv"
    info["gpu_env_path"] = ".venv-ocr-gpu-330"
    info["env_paths_distinct"] = ".venv" != ".venv-ocr-gpu-330"

    return info


def _get_glibc_version() -> str:
    try:
        result = subprocess.run(
            ["ldd", "--version"], capture_output=True, text=True, timeout=5
        )
        for line in (result.stdout or result.stderr).split("\n"):
            if "glibc" in line.lower() or "GLIBC" in line:
                import re
                m = re.search(r"(\d+\.\d+)", line)
                if m:
                    return m.group(1)
    except Exception:
        pass
    return "unknown"


def _get_nvcc_info() -> dict[str, Any]:
    info: dict[str, Any] = {}
    try:
        result = subprocess.run(
            ["nvcc", "--version"], capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            for line in result.stdout.split("\n"):
                if "release" in line.lower():
                    import re
                    m = re.search(r"release\s+(\d+\.\d+)", line)
                    if m:
                        info["cuda_version"] = m.group(1)
        else:
            info["error"] = result.stderr[:200]
    except Exception as e:
        info["error"] = str(e)
    return info


def _get_gpu_hardware_info() -> dict[str, Any]:
    info: dict[str, Any] = {}
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=driver_version,name,memory.total,compute_cap",
             "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split(", ")
            info["driver_version"] = parts[0] if len(parts) > 0 else ""
            info["gpu_name"] = parts[1] if len(parts) > 1 else ""
            info["memory_total"] = parts[2] if len(parts) > 2 else ""
            info["compute_capability"] = parts[3] if len(parts) > 3 else ""
            info["nvidia_smi_available"] = True
        else:
            info["nvidia_smi_available"] = False
            info["error"] = result.stderr[:200]
    except Exception as e:
        info["nvidia_smi_available"] = False
        info["error"] = str(e)

    # Also get CUDA version from nvidia-smi top line
    try:
        result = subprocess.run(
            ["nvidia-smi"], capture_output=True, text=True, timeout=10
        )
        for line in result.stdout.split("\n"):
            if "CUDA Version" in line:
                import re
                m = re.search(r"CUDA Version:\s*(\S+)", line)
                if m:
                    info["cuda_version_str"] = m.group(1)
                break
    except Exception:
        pass

    return info


def _format_markdown(checks: dict[str, Any]) -> str:
    lines = [
        "# GPU Environment Report",
        "",
        f"> Generated: {checks['timestamp']}",
        "",
        "## Summary",
        "",
        f"- Status: **{'✅ PASSED' if checks['summary']['status'] == 'passed' else '❌ FAILED'}**",
        f"- Checks passed: {checks['summary']['passed']}",
        f"- Checks failed: {checks['summary']['failed']}",
        "",
        "## System",
        "",
        f"- Python: {checks['system']['python_version']}",
        f"- Platform: {checks['system']['platform']}",
        f"- CUDA libraries: {checks['system']['cuda_libs_found']}",
        "",
        "## GPU Hardware",
        "",
    ]
    hw = checks["gpu_hardware"]
    if hw.get("nvidia_smi_available"):
        lines.extend([
            f"- Driver: {hw['driver_version']}",
            f"- GPU: {hw['gpu_name']}",
            f"- VRAM: {hw['memory_total']}",
            f"- Compute Capability: {hw['compute_capability']}",
            "",
        ])
    else:
        lines.append("- nvidia-smi not available\n")

    lines.extend([
        "## PaddlePaddle",
        "",
        f"- Imported: {checks['paddle'].get('imported', 'N/A')}",
        f"- Version: {checks['paddle'].get('version', 'N/A')}",
        f"- Compiled with CUDA: {checks['paddle'].get('compiled_with_cuda', 'N/A')}",
        "",
    ])
    if checks["paddle"].get("compiled_with_cuda"):
        lines.extend([
            f"- CUDA device count: {checks['paddle'].get('cuda_device_count', 'N/A')}",
            f"- Device name: {checks['paddle'].get('cuda_device_name', 'N/A')}",
            f"- Run check: {checks['paddle'].get('run_check', 'N/A')}",
            f"- Tensor test: {checks['paddle'].get('tensor_test_ms', 'N/A')} ms",
            "",
        ])

    lines.extend([
        "## PaddleOCR",
        "",
        f"- Imported: {checks['paddleocr'].get('imported', 'N/A')}",
        f"- Version: {checks['paddleocr'].get('version', 'N/A')}",
        "",
        "### Preflight Results",
        "",
    ])
    for name, ok in [
        ("paddle import", checks["paddle"].get("imported", False)),
        ("compiled_with_cuda", checks["paddle"].get("compiled_with_cuda", False)),
        ("cuda_device_count >= 1", checks["paddle"].get("cuda_device_count", 0) >= 1),
        ("paddle.utils.run_check", checks["paddle"].get("run_check") == "passed"),
        ("tensor computation", "tensor_test_ms" in checks["paddle"]),
        ("paddleocr import", checks["paddleocr"].get("imported", False)),
    ]:
        lines.append(f"| {'✅' if ok else '❌'} | {name} |")

    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(run())
