#!/usr/bin/env python3
"""Pipeline CI Runner — 三层 Gate 统一入口。

自动按 marker 分组运行测试，输出三份独立报告：
  - OPTIONS   (options_pipeline)   : 必须 100% pass, failure = CI fail
  - STRUCTURE (not ocr_deprecated) : 必须 100% pass, failure = CI fail
  - OCR       (ocr_dependency)     : failure = allowed, 仅标记 degraded

Usage:
    cd backend && python run_pipeline_ci.py
    cd backend && python run_pipeline_ci.py --verbose
    cd backend && python run_pipeline_ci.py --json       # JSON 输出
"""

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

# 项目根目录：脚本所在目录（backend/）
_PROJECT_ROOT = Path(__file__).resolve().parent


def _run_pytest(marker_expr: str, label: str) -> dict:
    """Run pytest with the given marker expression, return result dict."""
    start = time.time()
    cmd = [
        sys.executable, "-m", "pytest",
        "-m", marker_expr,
        "--tb=short", "-q",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=_PROJECT_ROOT)
    elapsed = round(time.time() - start, 2)

    stdout = result.stdout.strip()
    stderr = result.stderr.strip()

    # Parse summary from pytest output
    # Examples:
    # "36 passed in 0.85s"
    # "11 failed, 1891 passed in 19.65s"
    # "1028 passed, 11 deselected, 29 xfailed, 4 xpassed in 19.65s"
    summary_line = ""
    for line in (stdout + "\n" + stderr).split("\n"):
        if "passed" in line or "failed" in line:
            summary_line = line.strip()

    passed = 0
    failed = 0
    deselected = 0
    xfailed = 0
    xpassed = 0
    errors = 0

    # Parse counts from summary
    m_failed = re.search(r"(\d+)\s+failed", summary_line)
    if m_failed:
        failed = int(m_failed.group(1))
    m_passed = re.search(r"(\d+)\s+passed", summary_line)
    if m_passed:
        passed = int(m_passed.group(1))
    m_desel = re.search(r"(\d+)\s+deselected", summary_line)
    if m_desel:
        deselected = int(m_desel.group(1))
    m_xfail = re.search(r"(\d+)\s+xfailed", summary_line)
    if m_xfail:
        xfailed = int(m_xfail.group(1))
    m_xpass = re.search(r"(\d+)\s+xpassed", summary_line)
    if m_xpass:
        xpassed = int(m_xpass.group(1))
    m_errors = re.search(r"(\d+)\s+error", summary_line)
    if m_errors:
        errors = int(m_errors.group(1))

    # Filter warnings from stderr for cleaner output
    warning_lines = [l for l in stderr.split("\n") if "Warning" in l or "DeprecationWarning" in l or "UserWarning" in l]

    return {
        "label": label,
        "marker": marker_expr,
        "returncode": result.returncode,
        "passed": passed,
        "failed": failed,
        "deselected": deselected,
        "xfailed": xfailed,
        "xpassed": xpassed,
        "errors": errors,
        "elapsed": elapsed,
        "summary": summary_line,
        "warnings": warning_lines[:5],
        "stdout": stdout,
        "stderr": stderr,
    }


def _gate_status(results: list[dict]) -> tuple[list[dict], list[dict], dict | None]:
    """Extract gate-relevant results: (gate_results, gate_failures, ocr_result)."""
    gate_results = [r for r in results if r["label"] != "OCR"]
    gate_failures = [r for r in gate_results if r["returncode"] != 0]
    ocr_result = next((r for r in results if r["label"] == "OCR"), None)
    return gate_results, gate_failures, ocr_result


def _print_report(results: list[dict], verbose: bool = False) -> None:
    """Print human-readable CI report."""
    sep = "=" * 72
    print(f"\n{sep}")
    print(f"  Pipeline CI Report")
    print(f"{sep}")

    for r in results:
        tier_status = "✅ PASS" if r["returncode"] == 0 else "❌ FAIL"
        gate = "GATE" if r["label"] != "OCR" else "DEGRADED-OK"

        print(f"\n  ┌─ [{r['label']}] {tier_status} (gate={gate})")
        print(f"  │  Marker:       {r['marker']}")
        print(f"  │  Result:       {r['returncode']}")
        print(f"  │  Summary:      {r['summary']}")
        print(f"  │  Elapsed:      {r['elapsed']}s")
        if r["warnings"]:
            print(f"  │  Warnings:     {len(r['warnings'])}")
        print(f"  └─")

    # Overall gate status
    print(f"\n{sep}")
    gate_results, gate_failures, ocr_result = _gate_status(results)

    if not gate_failures:
        print(f"  ✅ GATE PASS: All pipeline tests pass")
    else:
        for g in gate_failures:
            print(f"  ❌ GATE FAIL: [{g['label']}] — {g['summary']}")

    if ocr_result and ocr_result["returncode"] != 0:
        print(f"  ⚠️  OCR DEGRADED: {ocr_result['failed']} test(s) failed (non-gate)")
    elif ocr_result:
        print(f"  ✅ OCR HEALTHY: All OCR dependency tests pass")

    total_passed = sum(r["passed"] for r in results)
    total_failed = sum(r["failed"] for r in results)
    total_time = sum(r["elapsed"] for r in results)
    print(f"\n  Total: {total_passed} passed, {total_failed} failed in {total_time:.1f}s")
    print(f"{sep}\n")

    # Verbose: show failed test detail
    if verbose:
        for r in results:
            if r["returncode"] != 0:
                print(f"\n  --- [{r['label']}] Failure Detail ---")
                # Show the last 20 lines of stdout (pytest output)
                lines = r["stdout"].split("\n")
                failed_lines = [l for l in lines if "FAILED" in l]
                if failed_lines:
                    for fl in failed_lines[:10]:
                        print(f"    {fl.strip()}")
                print()


def _print_json_report(results: list[dict]) -> None:
    """Print JSON-formatted CI report."""
    gate_results, gate_failures, ocr_result = _gate_status(results)

    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "overall": {
            "gate_pass": len(gate_failures) == 0,
            "ocr_healthy": ocr_result is not None and ocr_result["returncode"] == 0,
        },
        "tiers": results,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Pipeline CI Runner")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show failure detail")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    # ── Run three tiers ──
    tiers = [
        ("options_pipeline", "OPTIONS"),
        ("not ocr_deprecated", "STRUCTURE"),
        ("ocr_dependency", "OCR"),
    ]

    results = []
    for marker_expr, label in tiers:
        print(f"  Running [{label}] ... ", end="", flush=True)
        result = _run_pytest(marker_expr, label)
        status = "PASS" if result["returncode"] == 0 else "FAIL"
        print(f"{status} ({result['passed']}p/{result['failed']}f, {result['elapsed']}s)")
        results.append(result)

    # ── Output ──
    if args.json:
        _print_json_report(results)
    else:
        _print_report(results, verbose=args.verbose)

    # ── Exit code: gate tiers only ──
    _, gate_failures, _ = _gate_status(results)
    sys.exit(1 if gate_failures else 0)


if __name__ == "__main__":
    main()
