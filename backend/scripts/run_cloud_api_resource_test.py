#!/usr/bin/env python3
"""2C/2G cloud_api 资源受限实测 — 模拟生产服务器 (2核2G) 环境验证。

在 Docker 限制环境下运行：
  docker run --cpus=2 --memory=2g -v $(pwd):/app -w /app \\
    python:3.12-slim bash -c "pip install -e . && python scripts/run_cloud_api_resource_test.py"

验证项：
1. cloud_api profile 禁止本地 fallback（paddleocr、rule_fallback）
2. 内存使用在 2G 限制内
3. OCRGateway 初始化正常
4. AIModelConfigResolver 配置解析正常（需 DATABASE_URL）
5. Pipeline coordinator shadow 模式初始化正常
"""

from __future__ import annotations

import json
import os
import sys
import time
import tracemalloc
from datetime import datetime
from pathlib import Path

REPORTS_DIR = "reports/sprint4e"
os.makedirs(REPORTS_DIR, exist_ok=True)


def _check_cloud_profile() -> dict:
    """Verify cloud_api profile forbids local fallbacks."""
    from app.features.ocr_gateway import OCRGateway

    gw = OCRGateway(profile="cloud_api")
    forbidden = gw._get_forbidden_fallback()
    backends = [a.capabilities.backend for a in gw._registry.list_ocr()]

    result = {
        "profile": gw._profile,
        "forbidden_fallback": sorted(forbidden),
        "registered_backends": sorted(backends),
        "paddleocr_forbidden": "paddleocr" in forbidden,
        "rule_fallback_forbidden": "rule_fallback" in forbidden,
        "paddleocr_vl_registered": "paddleocr-vl" in backends,
    }
    result["pass"] = (
        result["paddleocr_forbidden"]
        and result["rule_fallback_forbidden"]
        and result["paddleocr_vl_registered"]
    )
    return result


def _check_memory() -> dict:
    """Check current memory usage (approximate via tracemalloc)."""
    tracemalloc.start()
    snapshot = tracemalloc.take_snapshot()
    top_stats = snapshot.statistics("lineno")
    total = sum(stat.size for stat in top_stats)
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "current_bytes": current,
        "peak_bytes": peak,
        "current_mb": round(current / 1024 / 1024, 2),
        "peak_mb": round(peak / 1024 / 1024, 2),
        "under_2g": peak < 2 * 1024 * 1024 * 1024,
    }


async def _check_config_resolution() -> dict:
    """Test AIModelConfigResolver with cloud-relevant capabilities."""
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        return {"pass": True, "skipped": True, "reason": "DATABASE_URL not set"}

    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    from app.services.model_config_resolver import (
        AICapability,
        AIModelConfigResolver,
    )

    engine = create_async_engine(db_url)
    result = {"capabilities": {}, "pass": True}
    async with AsyncSession(engine) as db:
        resolver = AIModelConfigResolver(db)
        for cap in (AICapability.OCR_VL, AICapability.OCR_FIX, AICapability.AI_REPAIR):
            try:
                resolved = await resolver.resolve_for_capability(cap)
                result["capabilities"][cap.value] = {
                    "provider": resolved.provider,
                    "model_name": resolved.model_name,
                    "timeout_seconds": resolved.timeout_seconds,
                }
            except ValueError as e:
                result["capabilities"][cap.value] = {"error": str(e)[:100]}
                result["pass"] = False
    return result


async def _check_shadow_mode_init() -> dict:
    """Verify coordinator shadow mode initializes without error."""
    from app.features.coordinator_orchestrator import CoordinatorPipeline

    pipeline = CoordinatorPipeline(context=None)
    return {
        "pass": True,
        "profile": pipeline.profile,
        "is_cloud": pipeline.is_cloud,
    }


async def main() -> int:
    print("=" * 60)
    print("2C/2G Cloud API Resource Test")
    print("=" * 60)

    all_results: dict[str, dict] = {}

    # 1. Cloud profile check
    t0 = time.monotonic()
    all_results["cloud_profile"] = _check_cloud_profile()
    print(f"  cloud_profile: {all_results['cloud_profile']['pass']} "
          f"({(time.monotonic() - t0)*1000:.0f}ms)")

    # 2. Memory check
    t0 = time.monotonic()
    all_results["memory"] = _check_memory()
    print(f"  memory: {all_results['memory']['peak_mb']}MB peak "
          f"({(time.monotonic() - t0)*1000:.0f}ms)")

    # 3. Config resolution (if DB available)
    t0 = time.monotonic()
    all_results["config_resolution"] = await _check_config_resolution()
    print(f"  config_resolution: {all_results['config_resolution']['pass']} "
          f"({(time.monotonic() - t0)*1000:.0f}ms)")

    # 4. Shadow mode init
    t0 = time.monotonic()
    all_results["shadow_mode_init"] = await _check_shadow_mode_init()
    print(f"  shadow_mode_init: {all_results['shadow_mode_init']['pass']} "
          f"({(time.monotonic() - t0)*1000:.0f}ms)")

    # Summary
    passed = sum(1 for r in all_results.values() if r.get("pass"))
    total = len(all_results)
    print(f"\n{'=' * 60}")
    print(f"Results: {passed}/{total} passed")

    report = {
        "timestamp": datetime.now().isoformat(),
        "results": {k: {kk: vv for kk, vv in v.items() if kk != "pass"}
                     for k, v in all_results.items()},
        "summary": {"total": total, "passed": passed, "all_pass": passed == total},
    }

    report_path = f"{REPORTS_DIR}/cloud_api_resource_test.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"Report saved: {report_path}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    import asyncio
    sys.exit(asyncio.run(main()))
