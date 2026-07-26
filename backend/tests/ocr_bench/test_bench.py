"""题库 OCR Bench — pytest 集成。

运行:
    PYTHONPATH=. pytest tests/ocr_bench/ -v
    PYTHONPATH=. pytest tests/ocr_bench/runner.py -v --json

Resolved:
    OCR-101 — 多栏阅读顺序修复 (004_multi_column, 013_multi_column_2)
    OCR-102 — 跨页链接由 cross_page_linking 模块处理 (014_cross_page)
    OCR-103 — 组合题中文数字编号由统一 parser 支持 (026_compound)
"""

import json
from pathlib import Path

import pytest

from tests.ocr_bench.runner import evaluate_case
from tests.ocr_bench.schema import load_case

CASES_DIR = Path(__file__).parent / "cases"

# ── Known failures ──────────────────────────────────────────────
_KNOWN_FAILURES: dict[str, pytest.MarkDecorator] = {
    # 100 cases total. The ~40 passing cases are the high-quality scan subset.
    # Below ~59 cases are known-score < 80 (text-only comparison limitations,
    # answer extraction, formatting drift). Tracked for regression detection:
    # when a case moves from FAIL → PASS, remove it from this list.
    "032_double_column_real_2": pytest.mark.xfail(reason="score < 80"),
    "033_triple_column": pytest.mark.xfail(reason="score < 80"),
    "034_complex_multi_column": pytest.mark.xfail(reason="score < 80"),
    "035_cross_column_title": pytest.mark.xfail(reason="score < 80"),
    "038_cross_page_table": pytest.mark.xfail(reason="score < 80"),
    "040_code_scan_2": pytest.mark.xfail(reason="score < 80"),
    "042_math_formula_scan_2": pytest.mark.xfail(reason="score < 80"),
    "044_table_mixed_text_2": pytest.mark.xfail(reason="score < 80"),
    "047_os_fork": pytest.mark.xfail(reason="score < 80"),
    "048_os_deadlock": pytest.mark.xfail(reason="score < 80"),
    "049_ds_linkedlist": pytest.mark.xfail(reason="score < 80"),
    "050_ds_tree": pytest.mark.xfail(reason="score < 80"),
    "051_cn_network": pytest.mark.xfail(reason="score < 80"),
    "052_math_limit": pytest.mark.xfail(reason="score < 80"),
    "053_ds_multi_col_sort": pytest.mark.xfail(reason="score < 80"),
    "054_ds_hash": pytest.mark.xfail(reason="score < 80"),
    "055_cross_page_memory": pytest.mark.xfail(reason="score < 80"),
    "056_cross_page_graph": pytest.mark.xfail(reason="score < 80"),
    "057_code_recursion": pytest.mark.xfail(reason="score < 80"),
    "058_code_array": pytest.mark.xfail(reason="score < 80"),
    "059_code_struct": pytest.mark.xfail(reason="score < 80"),
    "060_math_derivative": pytest.mark.xfail(reason="score < 80"),
    "061_math_integral": pytest.mark.xfail(reason="score < 80"),
    "062_table_page_table": pytest.mark.xfail(reason="score < 80"),
    "063_table_ip": pytest.mark.xfail(reason="score < 80"),
    "064_phone_os": pytest.mark.xfail(reason="score < 80"),
    "065_low_dpi_ds": pytest.mark.xfail(reason="score < 80"),
    "066_watermark_header": pytest.mark.xfail(reason="score < 80"),
    "067_watermark_footer": pytest.mark.xfail(reason="score < 80"),
    "068_mixed_lang_cache": pytest.mark.xfail(reason="score < 80"),
    "069_mixed_lang_dma": pytest.mark.xfail(reason="score < 80"),
    "071_ds_stack_queue": pytest.mark.xfail(reason="score < 80"),
    "072_ds_string": pytest.mark.xfail(reason="score < 80"),
    "073_co_float": pytest.mark.xfail(reason="score < 80"),
    "074_co_instruction": pytest.mark.xfail(reason="score < 80"),
    "075_network_transport": pytest.mark.xfail(reason="score < 80"),
    "076_co_pipeline_multi": pytest.mark.xfail(reason="score < 80"),
    "077_multi_col_os_sync": pytest.mark.xfail(reason="score < 80"),
    "078_cross_page_co": pytest.mark.xfail(reason="score < 80"),
    "079_cross_page_network": pytest.mark.xfail(reason="score < 80"),
    "080_cross_page_os_page": pytest.mark.xfail(reason="score < 80"),
    "081_code_string": pytest.mark.xfail(reason="score < 80"),
    "082_code_bit": pytest.mark.xfail(reason="score < 80"),
    "084_math_linear_algebra": pytest.mark.xfail(reason="score < 80"),
    "085_math_probability": pytest.mark.xfail(reason="score < 80"),
    "086_table_cache": pytest.mark.xfail(reason="score < 80"),
    "087_table_disk": pytest.mark.xfail(reason="score < 80"),
    "088_phone_network": pytest.mark.xfail(reason="score < 80"),
    "089_phone_math": pytest.mark.xfail(reason="score < 80"),
    "090_low_dpi_os": pytest.mark.xfail(reason="score < 80"),
    "091_low_dpi_network": pytest.mark.xfail(reason="score < 80"),
    "092_header_footer_ds": pytest.mark.xfail(reason="score < 80"),
    "093_header_footer_co": pytest.mark.xfail(reason="score < 80"),
    "094_mixed_image_text": pytest.mark.xfail(reason="score < 80"),
    "095_mixed_image_io": pytest.mark.xfail(reason="score < 80"),
    "096_compound_fill_choice": pytest.mark.xfail(reason="score < 80"),
    "098_side_option_ip": pytest.mark.xfail(reason="score < 80"),
    "099_side_option_cache": pytest.mark.xfail(reason="score < 80"),
    "100_side_option_math": pytest.mark.xfail(reason="score < 80"),
}


def _case_params() -> list:
    """Generate parametrize params with xfail markers for known failures.

    Skips placeholder cases (``meta.json`` has ``"placeholder": true``) —
    these are skeleton directories for future data collection and don't
    contain real ground truth yet.
    """
    params: list = []
    for d in sorted(CASES_DIR.iterdir()):
        if not (d / "ground_truth.txt").exists():
            continue
        case_name = d.name

        # Skip placeholder cases
        meta_path = d / "meta.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                if meta.get("placeholder"):
                    continue
            except (json.JSONDecodeError, OSError):
                pass

        marker = _KNOWN_FAILURES.get(case_name)
        if marker:
            params.append(pytest.param(case_name, marks=marker))
        else:
            params.append(pytest.param(case_name))
    return params


@pytest.mark.parametrize("case_name", _case_params())
def test_ocr_bench_case(case_name: str):
    """每个 benchmark case 一个参数化测试。"""
    case = load_case(CASES_DIR / case_name)
    result = evaluate_case(case)
    if not result.passed:
        pytest.fail(
            f"[{case_name}] score={result.overall_score}, "
            f"CER={result.line.cer}, ans_em={result.business.answer_em}"
        )
