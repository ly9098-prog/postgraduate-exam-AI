#!/usr/bin/env python3
"""OCR 导题验收脚本。

对真实样本执行 OCR 并评估导题质量。
样本需手动放置到 cases/ 目录下。

用法:
    # 标准验收
    python tests/ocr_acceptance/run_acceptance.py --case-dir tests/ocr_acceptance/cases

    # 严格模式（发布前检查）
    python tests/ocr_acceptance/run_acceptance.py --case-dir tests/ocr_acceptance/cases --strict

    # 输出报告到文件
    python tests/ocr_acceptance/run_acceptance.py --case-dir tests/ocr_acceptance/cases --report acceptance_report.json
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from typing import Any

# Ensure failure_classifier is importable regardless of invocation path
import sys
_script_dir = os.path.dirname(os.path.abspath(__file__))
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)
from failure_classifier import classify_acceptance_result  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Reference metrics (relaxed — used as guidance, not gates)
_REFERENCE_METRICS: dict[str, float] = {
    "question_count_recall": 0.95,
    "option_integrity": 0.98,
    "answer_match_rate": 0.96,
    "math_image_presence": 0.90,
    "code_symbol_preservation": 0.99,
    "table_structure_presence": 0.85,
    "manual_review_rate": 0.30,
}

# Tighter thresholds for strict mode (all ≥ reference — stricter = easier to fail)
_STRICT_METRICS: dict[str, float] = {
    "question_count_recall": 0.98,
    "option_integrity": 0.99,
    "answer_match_rate": 0.98,
    "math_image_presence": 0.95,
    "code_symbol_preservation": 1.00,
    "table_structure_presence": 0.92,
    "manual_review_rate": 0.20,
}


def _load_case_metadata(case_dir: str) -> dict | None:
    """Load case.json metadata if present."""
    meta_path = os.path.join(case_dir, "case.json")
    if not os.path.isfile(meta_path):
        return None
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load case metadata %s: %s", meta_path, e)
        return None


def _discover_cases(case_dir: str) -> dict[str, list[str]]:
    """Scan case_dir for subdirectories containing test files.

    Returns {case_name: [file_paths]}.
    """
    if not os.path.isdir(case_dir):
        logger.warning("Case directory %s not found", case_dir)
        return {}

    cases: dict[str, list[str]] = {}
    for entry in sorted(os.listdir(case_dir)):
        sub = os.path.join(case_dir, entry)
        if not os.path.isdir(sub):
            continue
        files: list[str] = []
        for f in sorted(os.listdir(sub)):
            path = os.path.join(sub, f)
            if os.path.isfile(path) and _is_supported(f):
                files.append(path)
        if files:
            cases[entry] = files
    return cases


def _is_supported(filename: str) -> bool:
    lower = filename.lower()
    return lower.endswith((".pdf", ".png", ".jpg", ".jpeg", ".txt"))


def _run_case_simple(
    case_name: str,
    files: list[str],
    metrics: dict[str, Any],
    strict: bool = False,
) -> dict[str, Any]:
    """Simple structural analysis of case files without running full pipeline.

    For actual OCR pipeline testing, this would call PaddleOCR and the
    import pipeline. For now, performs basic file-level quality checks.
    """
    case_dir = os.path.dirname(files[0]) if files else None
    case_meta = _load_case_metadata(case_dir) if case_dir else None

    result: dict[str, Any] = {
        "status": "skipped",
        "files": len(files),
        "question_count": 0,
        "case_metadata": case_meta,
        "note": "Manual execution required — place real samples in cases/ directory",
    }

    if files:
        total_bytes = sum(os.path.getsize(f) for f in files)
        result["total_bytes"] = total_bytes
        result["avg_bytes"] = total_bytes // len(files) if files else 0

    # Check each metric against reference
    metric_results: dict[str, Any] = {}
    ref = _STRICT_METRICS if strict else _REFERENCE_METRICS
    pass_ratio = 0.8  # 80% of reference = pass

    for metric_name, ref_value in ref.items():
        actual = metrics.get(metric_name)
        if actual is not None:
            passed = actual >= ref_value * pass_ratio
            metric_results[metric_name] = {
                "reference": ref_value,
                "actual": actual,
                "passed": passed,
            }

    if metric_results:
        result["metrics"] = metric_results
        all_passed = all(m["passed"] for m in metric_results.values())
        result["all_metrics_passed"] = all_passed
        if all_passed and result.get("status") == "skipped":
            result["status"] = "passed"

    if strict and metric_results:
        # In strict mode, any metric below 90% of reference is a fail
        failed_strict = [
            name for name, m in metric_results.items()
            if m["actual"] < m["reference"] * 0.9
        ]
        if failed_strict:
            result["strict_failures"] = failed_strict
            result["status"] = "failed"

    # ---- Failure classification (P6-3) ----
    if case_meta and metric_results:
        try:
            # Build acceptance_metrics dict from the computed metric_results
            acceptance_metrics = {
                name: m["actual"]
                for name, m in metric_results.items()
            }
            classification = classify_acceptance_result(
                case_meta=case_meta,
                pipeline_output=None,  # Populated when real pipeline is wired in
                acceptance_metrics=acceptance_metrics,
            )
            result["failure_classification"] = classification
            # Elevate status if classification indicates failure
            if classification.get("status") == "fail" and result.get("status") != "failed":
                result["status"] = "failed"
            elif classification.get("status") == "warn" and result.get("status") == "skipped":
                result["status"] = "warn"
        except Exception as exc:
            logger.warning("Failure classification failed for case '%s': %s", case_name, exc)

    return result


def run_acceptance(case_dir: str, strict: bool = False) -> dict[str, Any]:
    """Run acceptance tests for all discovered cases."""
    cases = _discover_cases(case_dir)
    if not cases:
        logger.warning("No test cases found in %s", case_dir)
        return {"status": "no_cases", "cases": {}, "summary": {}}

    logger.info("Found %d case types: %s", len(cases), ", ".join(cases.keys()))

    results: dict[str, Any] = {}
    for case_name, files in cases.items():
        logger.info("Running case '%s' (%d files)", case_name, len(files))
        metrics: dict[str, Any] = {}
        results[case_name] = _run_case_simple(case_name, files, metrics, strict=strict)

    total = len(results)
    passed = sum(1 for r in results.values() if r.get("status") == "passed")
    failed = sum(1 for r in results.values() if r.get("status") == "failed")
    warned = sum(1 for r in results.values() if r.get("status") == "warn")
    strict_fails = sum(
        1 for r in results.values() if r.get("strict_failures")
    )

    # Aggregate failure classification results across all cases
    failure_summary: dict[str, Any] = {
        "total_failures": 0,
        "high_severity": 0,
        "medium_severity": 0,
        "low_severity": 0,
        "failure_types": {},
    }
    for r in results.values():
        classification = r.get("failure_classification")
        if not classification:
            continue
        analysis = classification.get("failure_analysis") or {}
        failures = analysis.get("failures") or []
        failure_summary["total_failures"] += len(failures)
        for f in failures:
            sev = f.get("severity", "")
            if sev == "high":
                failure_summary["high_severity"] += 1
            elif sev == "medium":
                failure_summary["medium_severity"] += 1
            elif sev == "low":
                failure_summary["low_severity"] += 1
            ftype = f.get("type", "unknown")
            failure_summary["failure_types"][ftype] = failure_summary["failure_types"].get(ftype, 0) + 1

    summary = {
        "total_cases": total,
        "passed": passed,
        "failed": failed,
        "warned": warned,
        "skipped": total - passed - failed - warned,
        "mode": "strict" if strict else "standard",
    }
    if strict_fails:
        summary["strict_failures"] = strict_fails
    if failure_summary["total_failures"] > 0:
        summary["failure_classification"] = failure_summary

    return {
        "date": datetime.now().isoformat(),
        "cases": results,
        "summary": summary,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="OCR import acceptance test runner",
    )
    parser.add_argument(
        "--case-dir",
        default="tests/ocr_acceptance/cases",
        help="Directory containing case subdirectories",
    )
    parser.add_argument(
        "--report",
        default=None,
        help="Path to write acceptance report JSON",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Strict mode for pre-release checks",
    )
    args = parser.parse_args()

    report = run_acceptance(args.case_dir, strict=args.strict)

    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        logger.info("Report written to %s", args.report)

    print("\n" + json.dumps(report, ensure_ascii=False, indent=2))

    summary = report.get("summary", {})
    if summary.get("failed", 0) > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
