"""OCR Bench 运行器。

支持三种模式：
1. text-only: 加载 input.txt (OCR 输出) 与 ground_truth.txt 对比
2. reading-order: 当 meta.json 包含 ocr_regions 时，先通过 ReadingOrderResolver
   确定正确阅读顺序，再与 ground_truth 对比
3. live-OCR: 对 input.png/pdf 运行真实 OCR 管道，然后评估

运行:
    cd backend && PYTHONPATH=. python -m tests.ocr_bench.runner
    cd backend && PYTHONPATH=. python -m tests.ocr_bench.runner --json
    cd backend && PYTHONPATH=. python -m tests.ocr_bench.runner --case 001
    cd backend && PYTHONPATH=. python -m tests.ocr_bench.runner --live-ocr
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from app.core.document_ir import BBox, LineIR, PageIR, RegionIR
from app.features.reading_order import ReadingOrderResolver
from tests.ocr_bench.metrics import evaluate, scenario_pass_rate
from tests.ocr_bench.schema import (
    BenchmarkCase,
    MetricsResult,
    ScenarioBucket,
    discover_cases,
    load_case,
)

_CASES_DIR = Path(__file__).parent / "cases"


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run_text_only(case: BenchmarkCase) -> MetricsResult:
    """Text-only 模式：对比 input_text 与 ground_truth。"""
    if not case.ground_truth:
        return MetricsResult(
            case_id=case.case_id,
            scenario=case.scenario,
            overall_score=0.0,
            passed=False,
            details={"error": "No ground_truth.txt found"},
        )

    ocr_text = case.input_text or case.ground_truth

    return evaluate(
        case_id=case.case_id,
        scenario=case.scenario,
        gt=case.ground_truth,
        ocr=ocr_text,
        expected_qnumbers=case.expected_qnumbers,
        expected_options=case.expected_options,
        expected_answers=case.expected_answers,
    )


def run_text_with_reading_order(case: BenchmarkCase) -> MetricsResult:
    """Reading-Order 模式：先通过 ReadingOrderResolver 确定阅读顺序，再对比 GT。

    需要 case 的 meta.json 包含 ``ocr_regions`` 列表，每项含：
    - ``id``: region ID
    - ``text``: region 文本内容
    - ``bbox``: [x0, y0, x1, y1]
    - ``page_width``: 页面宽度
    - ``page_height``: 页面高度
    """
    if not case.ground_truth:
        return MetricsResult(
            case_id=case.case_id,
            scenario=case.scenario,
            overall_score=0.0,
            passed=False,
            details={"error": "No ground_truth.txt found"},
        )

    # Load meta.json directly for ocr_regions
    case_dir = Path(case.case_dir) if case.case_dir else Path(__file__).parent / "cases" / case.case_id
    meta_path = case_dir / "meta.json"
    if not meta_path.exists():
        return run_text_only(case)

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    ocr_regions = meta.get("ocr_regions")
    if not ocr_regions:
        return run_text_only(case)

    try:
        # Build PageIR from ocr_regions data
        page_width = float(ocr_regions[0].get("page_width", 800))
        page_height = float(ocr_regions[0].get("page_height", 1000))

        regions: list[RegionIR] = []
        for r_data in ocr_regions:
            bx = r_data["bbox"]
            bbox = BBox(float(bx[0]), float(bx[1]), float(bx[2]), float(bx[3]))
            region = RegionIR(
                region_id=r_data["id"],
                region_type="text",
                bbox=bbox,
                lines=[LineIR(text=r_data["text"], bbox=bbox)],
            )
            regions.append(region)

        page = PageIR(
            page_id=f"bench_{case.case_id}",
            page_index=0,
            width=page_width,
            height=page_height,
            regions=regions,
        )

        # Resolve reading order
        resolver = ReadingOrderResolver()
        result = resolver.resolve(page)

        # Reconstruct text in reading order
        ordered_text_parts: list[str] = []
        for region_id in result.ordered_region_ids:
            for region in regions:
                if region.region_id == region_id:
                    ordered_text_parts.append(region.text)
                    break

        ordered_ocr = "\n".join(ordered_text_parts)

    except Exception as exc:
        return MetricsResult(
            case_id=case.case_id,
            scenario=case.scenario,
            overall_score=0.0,
            passed=False,
            details={"error": f"Reading order resolution failed: {exc}"},
        )

    return evaluate(
        case_id=case.case_id,
        scenario=case.scenario,
        gt=case.ground_truth,
        ocr=ordered_ocr,
        expected_qnumbers=case.expected_qnumbers,
        expected_options=case.expected_options,
        expected_answers=case.expected_answers,
    )


def evaluate_case(case: BenchmarkCase) -> MetricsResult:
    """Evaluate a case using the best available mode.

    Prefers reading-order mode when ocr_regions are available in meta.json,
    falls back to text-only mode otherwise.
    """
    if not case.case_dir:
        return run_text_only(case)

    meta_path = Path(case.case_dir) / "meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("ocr_regions"):
            return run_text_with_reading_order(case)

    return run_text_only(case)


def run_live_ocr(case: BenchmarkCase, process_pool: bool = False) -> MetricsResult:
    """Live-OCR 模式：对 input image/PDF 运行 OCR 管道并评估。

    需要 PaddleOCR 和真实图片文件。
    """
    if not case.input_path:
        return MetricsResult(
            case_id=case.case_id,
            scenario=case.scenario,
            overall_score=0.0,
            passed=False,
            details={"error": "No input image/PDF for live-OCR"},
        )

    if not case.ground_truth:
        return MetricsResult(
            case_id=case.case_id,
            scenario=case.scenario,
            overall_score=0.0,
            passed=False,
            details={"error": "No ground_truth.txt for comparison"},
        )

    import os
    os.environ["OCR_USE_PROCESS_POOL"] = "1" if process_pool else "0"

    from app.features.pipeline_orchestrator import _ocr_scanned_pdf

    input_bytes = Path(case.input_path).read_bytes()

    start = time.monotonic()
    try:
        blocks = _ocr_scanned_pdf(input_bytes)
    except Exception as exc:
        return MetricsResult(
            case_id=case.case_id,
            scenario=case.scenario,
            overall_score=0.0,
            passed=False,
            duration_ms=(time.monotonic() - start) * 1000,
            details={"error": f"OCR pipeline failed: {exc}"},
        )

    duration_ms = (time.monotonic() - start) * 1000

    ocr_text = "\n".join(b.get("text", "") for b in blocks)

    return evaluate(
        case_id=case.case_id,
        scenario=case.scenario,
        gt=case.ground_truth,
        ocr=ocr_text,
        expected_qnumbers=case.expected_qnumbers,
        expected_options=case.expected_options,
        expected_answers=case.expected_answers,
        duration_ms=duration_ms,
    )


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def build_report(results: list[MetricsResult]) -> dict[str, Any]:
    """构建完整报告。"""
    n = len(results)
    passed = sum(1 for r in results if r.passed)
    avg_score = sum(r.overall_score for r in results) / max(n, 1)
    avg_cer = sum(r.line.cer for r in results) / max(n, 1)
    avg_ans_em = sum(r.business.answer_em for r in results) / max(n, 1)

    scenario_report = scenario_pass_rate(results)

    # Reading order summary
    avg_order_acc = sum(r.reading_order.pairwise_order_accuracy for r in results) / max(n, 1)
    avg_seq_match = sum(r.reading_order.sequence_exact_match for r in results) / max(n, 1)
    avg_qn_order = sum(r.reading_order.question_number_order_accuracy for r in results) / max(n, 1)
    avg_opt_order = sum(r.reading_order.option_order_accuracy for r in results) / max(n, 1)

    return {
        "summary": {
            "total_cases": n,
            "passed": passed,
            "pass_rate": round(passed / max(n, 1), 4) if n else 0.0,
            "avg_score": round(avg_score, 1),
            "avg_cer": round(avg_cer, 4),
            "avg_answer_em": round(avg_ans_em, 4),
            "avg_order_acc": round(avg_order_acc, 4),
            "avg_seq_match": round(avg_seq_match, 4),
            "avg_qn_order": round(avg_qn_order, 4),
            "avg_opt_order": round(avg_opt_order, 4),
        },
        "scenario_report": scenario_report,
        "results": [
            {
                "case_id": r.case_id,
                "scenario": r.scenario.value,
                "passed": r.passed,
                "overall_score": r.overall_score,
                "cer": r.line.cer,
                "wer": r.line.wer,
                "line_recall": r.line.line_recall,
                "line_precision": r.line.line_precision,
                "text_drop_rate": r.line.text_drop_rate,
                "question_number_em": r.business.question_number_em,
                "option_set_em": r.business.option_set_em,
                "answer_em": r.business.answer_em,
                "question_count_match": r.business.question_count_match,
                "bracket_balance_rate": r.code.bracket_balance_rate,
                "code_token_em": r.code.code_token_em,
                "duration_ms": r.duration_ms,
                "details": r.details,
            }
            for r in results
        ],
    }


def print_text_report(report: dict[str, Any]) -> None:
    """输出人类可读报告。"""
    s = report["summary"]
    print("\n" + "=" * 70)
    print("  OCR Bench 报告")
    print("=" * 70)
    print(f"  Cases:    {s['total_cases']}")
    print(f"  Passed:   {s['passed']}")
    print(f"  Pass rate: {s['pass_rate']:.1%}")
    print(f"  Avg score: {s['avg_score']}/100")
    print(f"  Avg CER:  {s['avg_cer']:.4f}")
    print(f"  Avg Ans EM: {s['avg_answer_em']:.4f}")
    print(f"  Avg Order Acc: {s.get('avg_order_acc', 0):.4f}")
    print(f"  Avg QN Order: {s.get('avg_qn_order', 0):.4f}")
    print(f"  Avg Opt Order: {s.get('avg_opt_order', 0):.4f}")

    # Scenario breakdown
    print(f"\n  {'Bucket':<28} {'Count':>6} {'Pass':>6} {'Rate':>7} {'Score':>7} {'CER':>8}")
    print("  " + "-" * 70)
    for bucket, br in sorted(report["scenario_report"].items()):
        print(
            f"  {bucket:<28} "
            f"{br['count']:>6} "
            f"{br['passed']:>6} "
            f"{br['pass_rate']:.0%} "
            f"{br['avg_score']:>7.1f} "
            f"{br['avg_cer']:>8.4f}"
        )

    # Detail
    print(f"\n  {'Case':<30} {'Pass?':>6} {'Score':>7} {'CER':>8} {'AnsEM':>7} {'Dur(ms)':>8}")
    print("  " + "-" * 70)
    for r in report["results"]:
        print(
            f"  {r['case_id']:<30} "
            f"{'PASS' if r['passed'] else 'FAIL':>6} "
            f"{r['overall_score']:>7.1f} "
            f"{r['cer']:>8.4f} "
            f"{r['answer_em']:>7.4f} "
            f"{r['duration_ms']:>8.1f}"
        )
        if r.get("details", {}).get("error"):
            print(f"    ERROR: {r['details']['error']}")

    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="OCR Bench Runner")
    parser.add_argument("--case", type=str, default=None, help="Only run specific case")
    parser.add_argument("--json", action="store_true", help="Output JSON report")
    parser.add_argument("--live-ocr", action="store_true", help="Run live OCR mode")
    parser.add_argument("--process-pool", action="store_true", help="Use process pool in live OCR")
    args = parser.parse_args()

    cases = discover_cases()
    if args.case:
        cases = [c for c in cases if c.case_id.startswith(args.case)]

    if not cases:
        print("No benchmark cases found.", file=sys.stderr)
        return 1

    results: list[MetricsResult] = []
    for case in cases:
        if args.live_ocr and case.input_path:
            result = run_live_ocr(case, process_pool=args.process_pool)
        else:
            result = evaluate_case(case)

        status = "PASS" if result.passed else "FAIL"
        print(f"  [{status}] {case.case_id} score={result.overall_score:.1f}", file=sys.stderr)
        results.append(result)

    report = build_report(results)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_text_report(report)

    has_fail = any(not r.passed for r in results)
    return 1 if has_fail else 0


if __name__ == "__main__":
    sys.exit(main())
