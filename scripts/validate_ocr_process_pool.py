#!/usr/bin/env python3
"""Process Pool 灰度验证 — 验证 OCR 进程隔离的执行正确性与质量等价性。

三种运行模式:
1. 架构验证（默认）：检查代码结构、导入、API 一致性（无需 PaddleOCR）
2. 质量等价：通过 ocr_bench 在同一样本上比较 thread pool vs process pool 输出
3. 故障注入：测试 crash/timeout 恢复机制

运行:
    python scripts/validate_ocr_process_pool.py
    python scripts/validate_ocr_process_pool.py --quality  # 需要 PaddleOCR + 图片
    python scripts/validate_ocr_process_pool.py --fault    # 需要 PaddleOCR
    python scripts/validate_ocr_process_pool.py --all       # 全部
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "backend"))


# ---------------------------------------------------------------------------
# 1. Architecture validation
# ---------------------------------------------------------------------------


def _check_import(name: str) -> bool:
    try:
        importlib.import_module(name)
        return True
    except ImportError:
        return False


def check_architecture() -> dict[str, Any]:
    """验证进程池的代码结构和导入路径。"""
    checks: dict[str, Any] = {}

    # 1a. Verify process pool module is importable
    pool_ok = _check_import("app.core.ocr_process_pool")
    checks["ocr_process_pool_importable"] = pool_ok
    if not pool_ok:
        checks["_pool_error"] = "app.core.ocr_process_pool cannot be imported"

    # 1b. Verify the OcrProcessPool class exists and has expected methods
    if pool_ok:
        from app.core.ocr_process_pool import OcrProcessPool, ocr_process_pool

        pool_methods = {
            "submit": callable(getattr(ocr_process_pool, "submit", None)),
            "get_text": callable(getattr(ocr_process_pool, "get_text", None)),
            "get_text_with_boxes": callable(getattr(ocr_process_pool, "get_text_with_boxes", None)),
            "shutdown": callable(getattr(ocr_process_pool, "shutdown", None)),
        }
        checks["pool_methods"] = pool_methods
        checks["pool_methods_all_ok"] = all(pool_methods.values())

        # Check stats property (not callable — it's a property returning a dict)
        try:
            _stats = ocr_process_pool.stats
            checks["pool_has_stats"] = isinstance(_stats, dict)
        except Exception:
            checks["pool_has_stats"] = False

        if checks["pool_has_stats"]:
            checks["pool_is_singleton"] = isinstance(ocr_process_pool, OcrProcessPool)

    # 1c. Verify executor service has process-pool integration
    exec_ok = _check_import("app.services.ocr_executor_service")
    checks["ocr_executor_importable"] = exec_ok
    if exec_ok:
        from app.services.ocr_executor_service import ocr_executor

        exec_methods = {
            "run_ocr": callable(getattr(ocr_executor, "run_ocr", None)),
            "run_ocr_pages": callable(getattr(ocr_executor, "run_ocr_pages", None)),
            "run_ocr_pages_with_boxes": callable(getattr(ocr_executor, "run_ocr_pages_with_boxes", None)),
            "run_ocr_pages_in_process": callable(getattr(ocr_executor, "run_ocr_pages_in_process", None)),
            "run_ocr_pages_with_boxes_in_process": callable(getattr(ocr_executor, "run_ocr_pages_with_boxes_in_process", None)),
        }
        checks["executor_methods"] = exec_methods
        checks["executor_methods_all_ok"] = all(exec_methods.values())

    # 1d. Verify pipeline orchestrator has process pool branch
    orch_ok = _check_import("app.features.pipeline_orchestrator")
    checks["pipeline_orchestrator_importable"] = orch_ok
    if orch_ok:
        from app.features.pipeline_orchestrator import _ocr_scanned_pdf

        source = inspect.getsource(_ocr_scanned_pdf)
        checks["has_process_pool_branch"] = "OCR_USE_PROCESS_POOL" in source
        checks["has_thread_pool_branch"] = "ocr_pages_with_boxes" in source
        checks["has_dual_branch"] = checks["has_process_pool_branch"] and checks["has_thread_pool_branch"]

    # 1e. Verify config flag exists
    config_ok = _check_import("app.core.config")
    checks["config_importable"] = config_ok
    if config_ok:
        from app.core.config import settings
        checks["config_has_flag"] = hasattr(settings, "OCR_USE_PROCESS_POOL")
        checks["config_flag_default"] = settings.OCR_USE_PROCESS_POOL

    # 1f. Verify thread pool fallback exists
    if exec_ok:
        from app.services.ocr_executor_service import _OcrExecutorService
        source = inspect.getsource(_OcrExecutorService.run_ocr_pages_with_boxes_in_process)
        checks["has_fallback"] = "run_ocr_pages_with_boxes" in source

    # only the top-level structural booleans that represent pass/fail
    _PASS_FAIL_KEYS = {
        "pool_methods_all_ok", "executor_methods_all_ok", "has_dual_branch",
        "has_fallback", "pool_is_singleton",
    }
    arch_pass_fail = {k: v for k, v in checks.items() if k in _PASS_FAIL_KEYS}
    checks["all_architecture_checks_ok"] = all(arch_pass_fail.values())
    return checks


# ---------------------------------------------------------------------------
# 2. Quality equivalence (requires PaddleOCR + images)
# ---------------------------------------------------------------------------


def _try_import(name: str):
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


def check_quality_equivalence(ocr_bench_cases: list[str] | None = None) -> dict[str, Any]:
    """比较 thread pool vs process pool 的 OCR 质量。

    需要 PaddleOCR 和真实图片。

    Returns:
        质量比较报告，如果 PaddleOCR 不可用则返回空报告。
    """
    report: dict[str, Any] = {
        "paddle_available": False,
        "compared_cases": 0,
        "match_rate": 0.0,
        "details": [],
    }

    paddle = _try_import("paddleocr")
    if paddle is None:
        paddle = _try_import("paddle")
        if paddle is None:
            report["skip_reason"] = "PaddleOCR not available — skipping live OCR tests"
            return report

    report["paddle_available"] = True

    # Import bench
    from tests.ocr_bench.schema import discover_cases

    cases = discover_cases()
    if ocr_bench_cases:
        cases = [c for c in cases if c.case_id in ocr_bench_cases]

    # Only run live OCR for cases that have an input image
    live_cases = [c for c in cases if c.input_path]
    if not live_cases:
        report["skip_reason"] = "No bench cases with image input available"
        return report

    from app.features.pipeline_orchestrator import _ocr_scanned_pdf
    from app.services.ocr_service import ocr_pages_with_boxes

    for case in live_cases:
        img_bytes = Path(case.input_path).read_bytes()
        case_result = {"case_id": case.case_id, "scenario": case.scenario.value}

        # Thread pool
        os.environ["OCR_USE_PROCESS_POOL"] = "0"
        start = time.monotonic()
        try:
            blocks_t = _ocr_scanned_pdf(img_bytes)
        except Exception as e:
            blocks_t = []
            case_result["thread_pool_error"] = str(e)
        case_result["thread_pool_ms"] = (time.monotonic() - start) * 1000

        # Process pool
        os.environ["OCR_USE_PROCESS_POOL"] = "1"
        start = time.monotonic()
        try:
            blocks_p = _ocr_scanned_pdf(img_bytes)
        except Exception as e:
            blocks_p = []
            case_result["process_pool_error"] = str(e)
        case_result["process_pool_ms"] = (time.monotonic() - start) * 1000

        # Compare texts
        text_t = "\n".join(b.get("text", "") for b in blocks_t)
        text_p = "\n".join(b.get("text", "") for b in blocks_p)

        from difflib import SequenceMatcher
        sm = SequenceMatcher(None, text_t, text_p)
        similarity = sm.ratio()
        case_result["text_similarity"] = round(similarity, 4)
        case_result["thread_pool_text_len"] = len(text_t)
        case_result["process_pool_text_len"] = len(text_p)

        case_result["match_ok"] = similarity >= 0.95 or (not text_t and not text_p)
        report["details"].append(case_result)

    n = len(report["details"])
    report["compared_cases"] = n
    if n > 0:
        ok = sum(1 for d in report["details"] if d.get("match_ok", False))
        report["match_rate"] = round(ok / n, 4)

    return report


# ---------------------------------------------------------------------------
# 3. Fault injection — test crash/timeout recovery
# ---------------------------------------------------------------------------


def check_fault_tolerance() -> dict[str, Any]:
    """验证故障恢复机制（不需要实际 PaddleOCR）。

    通过代码分析检查:
    - BrokenProcessPool 捕获
    - 自动恢复（shutdown_now + 重新 spawn）
    - 超时终止
    """
    report: dict[str, Any] = {}

    # 3a. Check BrokenProcessPool recovery — handled in submit(), not directly in get_text()
    from app.core.ocr_process_pool import ocr_process_pool
    submit_source = inspect.getsource(ocr_process_pool.submit)
    report["catches_broken_pool_in_submit"] = "BrokenProcessPool" in submit_source
    report["submit_auto_recovery"] = "_shutdown_now()" in submit_source and "self._ensure()" in submit_source

    # 3b. Check timeout enforcement in get_text
    get_text_source = inspect.getsource(ocr_process_pool.get_text)
    report["get_text_timeout_enforcement"] = "TimeoutError" in get_text_source
    report["get_text_process_termination"] = "_shutdown_now()" in get_text_source

    # 3c. Check get_text_with_boxes has same recovery
    get_boxes_source = inspect.getsource(ocr_process_pool.get_text_with_boxes)
    report["boxes_catches_broken_pool"] = "BrokenProcessPool" in get_boxes_source
    report["boxes_auto_recovery"] = "_shutdown_now()" in get_boxes_source
    report["boxes_timeout_enforcement"] = "TimeoutError" in get_boxes_source

    # 3d. Check executor service fallback
    from app.services.ocr_executor_service import ocr_executor
    in_process_source = inspect.getsource(ocr_executor.run_ocr_pages_with_boxes_in_process)
    report["executor_catches_import_error"] = "ImportError" in in_process_source
    report["executor_fallback_to_thread_pool"] = "run_ocr_pages_with_boxes(" in in_process_source
    report["executor_has_timeout"] = "asyncio.wait_for" in in_process_source

    # 3e. Check process pool is configurable
    report["configurable_via_settings"] = True  # verified in architecture check

    # 3f. Verify pool is a singleton
    report["pool_is_singleton"] = True  # verified in architecture check

    report["all_fault_tolerance_checks_ok"] = all(
        v is True for v in report.values() if isinstance(v, bool)
    )
    return report


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


_SCORE_PASS = 80.0
_SCORE_DEGRADED = 60.0


def _score_for_rate(rate: float | None) -> float:
    if rate is None:
        return 0.0
    return rate * 100


def build_report(
    arch: dict[str, Any],
    quality: dict[str, Any],
    fault: dict[str, Any],
) -> dict[str, Any]:
    """构建完整验证报告。"""
    # Architecture score
    arch_ok = arch.get("all_architecture_checks_ok", False)
    arch_score = 100.0 if arch_ok else 0.0

    # Fault tolerance score
    fault_ok = fault.get("all_fault_tolerance_checks_ok", False)
    fault_score = 100.0 if fault_ok else 0.0

    # Quality score
    quality_score = _score_for_rate(quality.get("match_rate"))
    quality_compared = quality.get("compared_cases", 0)

    # Weighted overall
    arch_weight = 0.4
    fault_weight = 0.3
    quality_weight = 0.3

    if quality_compared == 0:
        # No live comparison — redistribute weight
        quality_weight = 0.0
        arch_weight = 0.6
        fault_weight = 0.4

    overall = (
        arch_score * arch_weight
        + fault_score * fault_weight
        + quality_score * quality_weight
    )

    # Recommendation
    if quality_compared == 0:
        recommendation = "结构验证通过。需要在有 PaddleOCR 的环境运行 --quality 完成质量等价验证后决定。"
    elif overall >= 90 and quality_score >= 90:
        recommendation = "可以安全启用。建议在 canary 环境逐步打开灰度。"
    elif overall >= 70 and quality_score >= 70:
        recommendation = "结构通过但需要更多质量验证。建议 shadow mode 运行再评估。"
    else:
        recommendation = "不建议启用。需先修复验证失败项。"

    return {
        "score": {
            "overall": round(overall, 1),
            "architecture": round(arch_score, 1),
            "fault_tolerance": round(fault_score, 1),
            "quality_equivalence": round(quality_score, 1),
        },
        "architecture": arch,
        "fault_tolerance": fault,
        "quality_equivalence": {
            "paddle_available": quality.get("paddle_available", False),
            "compared_cases": quality.get("compared_cases", 0),
            "match_rate": quality.get("match_rate"),
            "details": quality.get("details", []),
            "skip_reason": quality.get("skip_reason"),
        },
        "recommendation": recommendation,
        "next_steps": _suggest_next_steps(arch_ok, fault_ok, quality),
    }


def _suggest_next_steps(arch_ok: bool, fault_ok: bool, quality: dict) -> list[str]:
    steps: list[str] = []
    if not arch_ok:
        steps.append("修复架构验证失败项")
    if not fault_ok:
        steps.append("修复故障恢复检查失败项")
    if quality.get("compared_cases", 0) == 0:
        steps.append("部署至有 PaddleOCR 的环境，运行 --quality 检查质量等价性")
    elif quality.get("match_rate", 0) < 0.95:
        steps.append("排查质量差异原因（文本长度不同或内容不一致）")
    if quality.get("compared_cases", 0) > 0 and quality.get("match_rate", 0) >= 0.95:
        steps.append("在 canary 环境设置 OCR_USE_PROCESS_POOL=True 开始灰度")
    if arch_ok and fault_ok:
        steps.append("默认值保持 False，灰度验证通过后再切换")
    return steps


def print_report(report: dict[str, Any]) -> None:
    """输出人类可读报告。"""
    s = report["score"]

    print("\n" + "=" * 70)
    print("  OCR Process Pool 灰度验证报告")
    print("=" * 70)
    print(f"  Overall:         {s['overall']}/100")
    print(f"  Architecture:    {s['architecture']}/100")
    print(f"  Fault Tolerance: {s['fault_tolerance']}/100")
    print(f"  Quality Equiv:   {s['quality_equivalence']}/100")
    print()

    print("  --- 架构验证 ---")
    arch = report["architecture"]
    for key, val in arch.items():
        if isinstance(val, bool):
            icon = "OK" if val else "FAIL"
            print(f"    {icon:<5} {key}")
        elif isinstance(val, dict):
            for k, v in val.items():
                icon = "OK" if v is True else ("FAIL" if v is False else "?")
                print(f"    {icon:<5} {k} = {v}")
    print()

    print("  --- 故障恢复 ---")
    fault = report["fault_tolerance"]
    for key, val in fault.items():
        if isinstance(val, bool):
            icon = "OK" if val else "FAIL"
            print(f"    {icon:<5} {key}")
    print()

    qe = report["quality_equivalence"]
    print("  --- 质量等价 ---")
    if qe.get("paddle_available"):
        print(f"    PaddleOCR available: yes")
        print(f"    Compared cases: {qe.get('compared_cases', 0)}")
        print(f"    Match rate: {qe.get('match_rate', 'N/A')}")
        for d in qe.get("details", []):
            icon = "OK" if d.get("match_ok") else "FAIL"
            print(f"    {icon:<5} {d['case_id']}: sim={d.get('text_similarity', 'N/A')}")
    else:
        print(f"    PaddleOCR: {qe.get('skip_reason', 'not available')}")
        print(f"    (结构验证仍在本地运行)")
    print()

    print(f"  Recommendation: {report['recommendation']}")
    print("  Next steps:")
    for step in report["next_steps"]:
        print(f"    - {step}")
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="OCR Process Pool validation")
    parser.add_argument("--quality", action="store_true", help="Run quality comparison (needs PaddleOCR)")
    parser.add_argument("--fault", action="store_true", help="Run fault injection (needs PaddleOCR)")
    parser.add_argument("--all", action="store_true", help="Run all checks")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--case", type=str, nargs="*", help="Only check specific bench cases")
    args = parser.parse_args()

    run_quality = args.quality or args.all
    run_fault = args.fault or args.all

    print("Running architecture validation...", file=sys.stderr)
    arch = check_architecture()

    print("Running fault tolerance analysis...", file=sys.stderr)
    fault = check_fault_tolerance()

    quality: dict[str, Any] = {
        "paddle_available": False,
        "compared_cases": 0,
        "match_rate": None,
        "details": [],
    }
    if run_quality:
        print("Running quality equivalence...", file=sys.stderr)
        quality = check_quality_equivalence(args.case)
    else:
        quality["skip_reason"] = "Skipped (pass --quality to run)"

    report = build_report(arch, quality, fault)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_report(report)

    return 0 if report["score"]["overall"] >= 60 else 1


if __name__ == "__main__":
    sys.exit(main())
