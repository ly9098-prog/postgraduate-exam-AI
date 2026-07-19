"""OCR 评测脚本：对比 OCR 输出与人工标注，计算质量指标。

运行方式:
    # structure-only（默认）
    cd backend && PYTHONPATH=. python -m tests.ocr_eval.eval_ocr

    # live-ocr（需 PaddleOCR）
    cd backend && PYTHONPATH=. python -m tests.ocr_eval.eval_ocr --live-ocr

    # 作为 pytest
    PYTHONPATH=backend pytest backend/tests/ocr_eval/eval_ocr.py -v
"""
import argparse
import json
import os
import sys
from pathlib import Path

import pytest

from tests.ocr_eval.metrics import (
    character_error_rate,
    line_precision,
    line_recall,
    text_drop_rate,
)

SAMPLES_DIR = Path(__file__).parent / "samples"

STATUS_PASS = "PASS"
STATUS_DEGRADED = "DEGRADED"
STATUS_FAIL = "FAIL"


def _status_from_cer(cer: float) -> str:
    if cer < 0.05:
        return STATUS_PASS
    if cer < 0.2:
        return STATUS_DEGRADED
    return STATUS_FAIL


def discover_samples(sample_filter: str | None = None) -> list[Path]:
    """发现所有样本目录。"""
    if not SAMPLES_DIR.exists():
        return []
    samples = sorted(
        d for d in SAMPLES_DIR.iterdir()
        if d.is_dir() and (d / "ground_truth.txt").exists()
    )
    if sample_filter:
        samples = [s for s in samples if s.name.startswith(sample_filter)]
    return samples


def evaluate_sample(sample_dir: Path, live_ocr: bool = False) -> dict:
    """评估单个样本，返回指标字典。"""
    gt_path = sample_dir / "ground_truth.txt"
    ocr_path = sample_dir / "ocr_output.txt"
    meta_path = sample_dir / "meta.json"

    gt_text = gt_path.read_text(encoding="utf-8").strip()

    if live_ocr:
        image_path = sample_dir / "image.png"
        if not image_path.exists():
            return {
                "sample": sample_dir.name,
                "error": "image.png not found for live-ocr mode",
            }
        ocr_text = _run_live_ocr(image_path)
        ocr_path.write_text(ocr_text, encoding="utf-8")
    else:
        if not ocr_path.exists():
            return {
                "sample": sample_dir.name,
                "error": "ocr_output.txt not found (use --live-ocr to generate)",
            }
        ocr_text = ocr_path.read_text(encoding="utf-8").strip()

    meta = {}
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))

    cer = character_error_rate(gt_text, ocr_text)
    gt_lines = [l for l in gt_text.split("\n") if l.strip()]
    ocr_lines = [l for l in ocr_text.split("\n") if l.strip()]
    recall_matched, recall_total = line_recall(gt_lines, ocr_lines)
    precision_matched, precision_total = line_precision(gt_lines, ocr_lines)
    drop_rate = text_drop_rate(gt_text, ocr_text)

    return {
        "sample": sample_dir.name,
        "cer": round(cer, 4),
        "line_recall": f"{recall_matched}/{recall_total}",
        "line_precision": f"{precision_matched}/{precision_total}",
        "text_drop_rate": round(drop_rate, 4),
        "status": _status_from_cer(cer),
        "failure_type": meta.get("failure_type", "unknown"),
        "description": meta.get("description", ""),
    }


def _run_live_ocr(image_path: Path) -> str:
    """使用 PaddleOCR 对图片执行实际 OCR。"""
    from app.services.ocr_service import ocr_image

    image_bytes = image_path.read_bytes()
    return ocr_image(image_bytes)


def print_report(results: list[dict]) -> None:
    """输出文本报告。"""
    print("\n=== OCR Evaluation Report ===\n")
    for r in results:
        if "error" in r:
            print(f"  {r['sample']}:  ERROR - {r['error']}")
            continue
        recall = r["line_recall"]
        print(
            f"  {r['sample']}:  "
            f"CER={r['cer']:.4f}  "
            f"LineRecall={recall}  "
            f"DropRate={r['text_drop_rate']:.4f}  "
            f"[{r['status']}]"
        )

    print("\n---")
    valid = [r for r in results if "error" not in r]
    if valid:
        avg_cer = sum(r["cer"] for r in valid) / len(valid)
        pass_count = sum(1 for r in valid if r["status"] == STATUS_PASS)
        degraded_count = sum(1 for r in valid if r["status"] == STATUS_DEGRADED)
        fail_count = sum(1 for r in valid if r["status"] == STATUS_FAIL)
        print(
            f"Average CER: {avg_cer:.4f} | "
            f"Samples: {len(valid)} | "
            f"Pass: {pass_count} | "
            f"Degraded: {degraded_count} | "
            f"Fail: {fail_count}"
        )
    else:
        print("No valid samples evaluated.")
    print()


def print_json_report(results: list[dict]) -> None:
    """输出 JSON 报告。"""
    valid = [r for r in results if "error" not in r]
    summary = {}
    if valid:
        summary = {
            "average_cer": round(sum(r["cer"] for r in valid) / len(valid), 4),
            "total_samples": len(valid),
            "pass": sum(1 for r in valid if r["status"] == STATUS_PASS),
            "degraded": sum(1 for r in valid if r["status"] == STATUS_DEGRADED),
            "fail": sum(1 for r in valid if r["status"] == STATUS_FAIL),
        }
    print(json.dumps({"results": results, "summary": summary}, ensure_ascii=False, indent=2))


# --- pytest integration ---

def _sample_ids():
    return [s.name for s in discover_samples()]


@pytest.mark.parametrize("sample_name", _sample_ids())
def test_ocr_sample(sample_name: str):
    """pytest: 每个样本一个 test case。已知失败样本标记 xfail。"""
    sample_dir = SAMPLES_DIR / sample_name
    meta_path = sample_dir / "meta.json"
    meta = {}
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))

    result = evaluate_sample(sample_dir, live_ocr=False)
    if "error" in result:
        pytest.skip(result["error"])

    is_known_failure = meta.get("failure_type", "clean") != "clean"
    if result["status"] == STATUS_FAIL:
        if is_known_failure:
            pytest.xfail(
                reason=f"OCR-100: Known failure ({meta.get('failure_type')}): CER={result['cer']}",
            )
        else:
            pytest.fail(
                f"Sample {sample_name}: CER={result['cer']} exceeds threshold 0.2"
            )


# --- CLI entry point ---

def main():
    parser = argparse.ArgumentParser(description="OCR 评测工具")
    parser.add_argument("--live-ocr", action="store_true", help="使用真实 PaddleOCR 识别图片")
    parser.add_argument("--sample", type=str, default=None, help="只评测指定样本（前缀匹配）")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式报告")
    args = parser.parse_args()

    live_ocr = args.live_ocr or os.environ.get("OCR_EVAL_LIVE") == "1"

    samples = discover_samples(args.sample)
    if not samples:
        print("No samples found.", file=sys.stderr)
        sys.exit(1)

    results = [evaluate_sample(s, live_ocr=live_ocr) for s in samples]

    if args.json:
        print_json_report(results)
    else:
        print_report(results)

    valid = [r for r in results if "error" not in r]
    if any(r["status"] == STATUS_FAIL for r in valid):
        sys.exit(1)


if __name__ == "__main__":
    main()
