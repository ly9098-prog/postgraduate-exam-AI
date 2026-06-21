#!/usr/bin/env python3
"""OCR 导题验收脚本。

对真实样本执行 OCR 并评估导题质量。
样本需手动放置到 cases/ 目录下。

用法:
    python tests/ocr_acceptance/run_acceptance.py --case-dir tests/ocr_acceptance/cases
    python tests/ocr_acceptance/run_acceptance.py --case-dir tests/ocr_acceptance/cases --report acceptance_report.json
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from typing import Any

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
) -> dict[str, Any]:
    """Simple structural analysis of case files without running full pipeline.

    For actual OCR pipeline testing, this would call PaddleOCR and the
    import pipeline. For now, performs basic file-level quality checks.
    """
    result: dict[str, Any] = {
        "status": "skipped",
        "files": len(files),
        "question_count": 0,
        "note": "Manual execution required — place samples in cases/ directory",
    }

    if files:
        total_bytes = sum(os.path.getsize(f) for f in files)
        result["total_bytes"] = total_bytes
        result["avg_bytes"] = total_bytes // len(files) if files else 0

    # Check each metric against reference
    metric_results: dict[str, Any] = {}
    for metric_name, ref_value in _REFERENCE_METRICS.items():
        actual = metrics.get(metric_name)
        if actual is not None:
            passed = actual >= ref_value * 0.8  # 80% of reference = pass
            metric_results[metric_name] = {
                "reference": ref_value,
                "actual": actual,
                "passed": passed,
            }

    if metric_results:
        result["metrics"] = metric_results
        result["all_metrics_passed"] = all(
            m["passed"] for m in metric_results.values()
        )

    return result


def run_acceptance(case_dir: str) -> dict[str, Any]:
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
        results[case_name] = _run_case_simple(case_name, files, metrics)

    total = len(results)
    passed = sum(1 for r in results.values() if r.get("status") == "passed")
    failed = sum(1 for r in results.values() if r.get("status") == "failed")

    summary = {
        "total_cases": total,
        "passed": passed,
        "failed": failed,
        "skipped": total - passed - failed,
    }

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
    args = parser.parse_args()

    report = run_acceptance(args.case_dir)

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
