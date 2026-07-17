"""Bench 扩展数据生成脚本 — 为新增 case 类型创建占位目录。

运行:
    python scripts/generate_bench_expansion.py
"""

import json
import os
import sys

CASES = [
    ("031_double_column_real", "double_column", "真实双栏题目页",
     {"expected_questions": 4, "tags": ["double_column", "real_world"]}),
    ("032_double_column_real_2", "double_column", "真实双栏题目页2",
     {"expected_questions": 4, "tags": ["double_column", "real_world"]}),
    ("033_triple_column", "triple_column", "三栏布局",
     {"expected_questions": 6, "tags": ["triple_column"]}),
    ("034_complex_multi_column", "double_column", "复杂多栏含跨栏标题",
     {"expected_questions": 5, "tags": ["multi_column", "cross_column_title"]}),
    ("035_cross_column_title", "single_column", "跨栏标题",
     {"expected_questions": 3, "tags": ["cross_column_title"]}),
    ("036_cross_page_3", "cross_page", "跨页题目变体",
     {"expected_questions": 3, "tags": ["cross_page", "merge"]}),
    ("037_cross_page_code", "cross_page", "跨页代码题",
     {"expected_questions": 2, "tags": ["cross_page", "code"]}),
    ("038_cross_page_table", "cross_page", "跨页表格题",
     {"expected_questions": 2, "tags": ["cross_page", "table"]}),
    ("039_code_scan", "code_scan", "代码扫描件",
     {"expected_questions": 3, "tags": ["code", "scan"]}),
    ("040_code_scan_2", "code_scan", "代码扫描件2",
     {"expected_questions": 2, "tags": ["code", "scan"]}),
    ("041_math_formula_scan", "math_scan", "数学公式扫描件",
     {"expected_questions": 4, "tags": ["math", "formula", "scan"]}),
    ("042_math_formula_scan_2", "math_scan", "数学公式扫描件2",
     {"expected_questions": 3, "tags": ["math", "formula", "scan"]}),
    ("043_table_mixed_text", "table_text", "表格穿插正文",
     {"expected_questions": 3, "tags": ["table", "mixed"]}),
    ("044_table_mixed_text_2", "table_text", "表格穿插正文2",
     {"expected_questions": 2, "tags": ["table", "mixed"]}),
    ("045_phone_photo_2", "phone_photo", "手机拍照变体",
     {"expected_questions": 3, "tags": ["phone", "photo", "real_world"]}),
    ("046_low_dpi_2", "low_dpi", "低DPI变体",
     {"expected_questions": 3, "tags": ["low_dpi", "degraded"]}),
]


def make_gt(case_id: str, n: int) -> str:
    lines: list[str] = []
    for qn in range(1, n + 1):
        lines.append(f"{qn}. placeholder question {qn}")
        lines.append("A. option_a")
        lines.append("B. option_b")
        if qn % 2 == 0:
            lines.append("C. option_c")
            lines.append("D. option_d")
        answer = "A" if qn % 2 == 0 else "B"
        lines.append(f"答案：{answer}")
        if qn < n:
            lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    basedir = os.path.join(
        os.path.dirname(__file__) or ".",
        "..", "tests", "ocr_bench", "cases",
    )
    basedir = os.path.normpath(basedir)

    created = 0
    for case_id, scenario, desc, extra in CASES:
        case_dir = os.path.join(basedir, case_id)
        os.makedirs(case_dir, exist_ok=True)

        meta = {
            "case_id": case_id,
            "scenario": scenario,
            "subject": "exam408",
            "description": f"{desc} — 占位模板，待补充真实数据",
            "placeholder": True,
            "date_added": "2026-07-17",
            "has_real_image": False,
            "tags": extra["tags"],
            "expected_questions": extra["expected_questions"],
            "expected_qnumbers": list(range(1, extra["expected_questions"] + 1)),
            "expected_answers": {},
        }

        with open(os.path.join(case_dir, "meta.json"), "w") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        with open(os.path.join(case_dir, "ground_truth.txt"), "w") as f:
            f.write(make_gt(case_id, extra["expected_questions"]))

        with open(os.path.join(case_dir, "input.txt"), "w") as f:
            f.write(f"# Placeholder OCR input for {case_id}\n")

        created += 1

    print(f"Created {created} expansion case directories in {basedir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
