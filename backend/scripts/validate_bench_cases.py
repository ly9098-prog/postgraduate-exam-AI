"""Bench 数据标注检查器。

验证 case 目录的完整性：
- 必需的 meta.json / input.txt / ground_truth.txt 是否存在
- meta.json 中的文件路径是否有效
- 期望题号与实际 ground_truth 是否匹配
- ground_truth 格式一致性

用法:
    python scripts/validate_bench_cases.py [cases_dir]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def check_case(case_dir: Path) -> dict:
    """Check a single case directory for completeness and consistency."""
    result = {
        "case_id": case_dir.name,
        "errors": [],
        "warnings": [],
        "score": 1.0,
    }

    # Required files
    meta_path = case_dir / "meta.json"
    input_path = case_dir / "input.txt"
    gt_path = case_dir / "ground_truth.txt"

    for path, name in [(meta_path, "meta.json"), (input_path, "input.txt"), (gt_path, "ground_truth.txt")]:
        if not path.exists():
            result["errors"].append(f"Missing required file: {name}")
        elif path.stat().st_size == 0:
            result["warnings"].append(f"Empty file: {name}")

    # Meta validation
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            _check_meta(meta, result, case_dir)
        except json.JSONDecodeError as e:
            result["errors"].append(f"Invalid meta.json: {e}")

    # Ground truth validation
    if gt_path.exists():
        _check_ground_truth(gt_path, result)

    # Input validation
    if input_path.exists():
        _check_input(input_path, result)

    if result["errors"]:
        result["score"] = max(0.0, 1.0 - len(result["errors"]) * 0.25)
    if result["warnings"]:
        result["score"] = max(0.0, result["score"] - len(result["warnings"]) * 0.1)

    return result


def _check_meta(meta: dict, result: dict, case_dir: Path) -> None:
    required_keys = ["scenario", "subject", "expected_questions"]
    for key in required_keys:
        if key not in meta:
            result["errors"].append(f"meta.json missing required key: {key}")

    # Validate ocr_regions if present
    ocr_regions = meta.get("ocr_regions", [])
    if ocr_regions:
        for i, r in enumerate(ocr_regions):
            if "id" not in r:
                result["errors"].append(f"ocr_regions[{i}] missing 'id'")
            if "bbox" not in r or len(r["bbox"]) != 4:
                result["errors"].append(f"ocr_regions[{i}] missing valid bbox")
            if "text" not in r:
                result["warnings"].append(f"ocr_regions[{i}] missing 'text'")

    # Validate expected_region_order
    region_order = meta.get("expected_region_order", [])
    if region_order and ocr_regions:
        region_ids = {r["id"] for r in ocr_regions}
        for rid in region_order:
            if rid not in region_ids:
                result["errors"].append(
                    f"expected_region_order contains unknown id: {rid}"
                )

    # Validate optional image paths
    for field in ("input_image", "input_pdf"):
        path_val = meta.get(field)
        if path_val:
            full_path = case_dir / path_val
            if not full_path.exists():
                result["warnings"].append(f"Referenced {field} not found: {path_val}")


def _check_ground_truth(gt_path: Path, result: dict) -> None:
    text = gt_path.read_text(encoding="utf-8")
    lines = text.strip().split("\n")

    if not text.strip():
        result["errors"].append("ground_truth.txt is empty")
        return

    if len(lines) < 4:
        result["warnings"].append("ground_truth.txt has fewer than 4 lines")

    # Check for question numbers (numeric prefixes)
    qn_count = len(re.findall(r"^\d+\s*[.、)）]", text, re.MULTILINE))
    meta_path = gt_path.parent / "meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        expected = meta.get("expected_questions", 0)
        if qn_count != expected and qn_count > 0:
            result["warnings"].append(
                f"ground_truth has {qn_count} questions, meta expects {expected}"
            )

    # Check for option patterns
    opt_count = len(re.findall(r"^[A-D]\s*[.、:：)）]", text, re.MULTILINE))
    if opt_count == 0:
        result["warnings"].append("ground_truth has no option lines (expected for non-choice)")


def _check_input(input_path: Path, result: dict) -> None:
    text = input_path.read_text(encoding="utf-8").strip()
    if not text:
        result["warnings"].append("input.txt is empty")


def main() -> int:
    cases_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        Path(__file__).parent.parent / "tests" / "ocr_bench" / "cases"
    )
    if not cases_dir.exists():
        print(f"Cases directory not found: {cases_dir}", file=sys.stderr)
        return 1

    case_dirs = sorted(cases_dir.iterdir())
    if not case_dirs:
        print(f"No case directories found in {cases_dir}", file=sys.stderr)
        return 1

    results = []
    has_errors = False
    for d in case_dirs:
        if not d.is_dir():
            continue
        r = check_case(d)
        results.append(r)
        status = "PASS" if not r["errors"] else "FAIL"
        print(f"  [{status}] {r['case_id']:30s} score={r['score']:.2f}")
        if r["errors"]:
            has_errors = True
            for e in r["errors"]:
                print(f"         ERROR: {e}")
        for w in r["warnings"]:
            print(f"         WARN:  {w}")

    total = len(results)
    passed = sum(1 for r in results if not r["errors"])
    placeholders = 0
    for d in case_dirs:
        if not d.is_dir():
            continue
        meta_path = d / "meta.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                if meta.get("placeholder"):
                    placeholders += 1
            except (json.JSONDecodeError, OSError):
                pass
    valid = total - placeholders
    invalid = total - passed

    print(f"\n  Summary: {total} cases, {valid} valid, {placeholders} placeholder, {invalid} invalid")
    print(f"  {passed} passed, {total - passed} failed")
    return 1 if has_errors else 0


if __name__ == "__main__":
    sys.exit(main())
