"""OCR 回归测试运行器 — 遍历 fixtures，运行完整管道，与 expected.txt 对比。

运行方式:
    # 回归测试（全部 case）
    cd backend && PYTHONPATH=. python -m tests.ocr_regression.runner

    # 生成/更新基线
    cd backend && PYTHONPATH=. python -m tests.ocr_regression.runner --baseline

    # 单 case
    cd backend && PYTHONPATH=. python -m tests.ocr_regression.runner --case 001

    # JSON 输出
    cd backend && PYTHONPATH=. python -m tests.ocr_regression.runner --json

    # 作为 pytest
    PYTHONPATH=. pytest tests/ocr_regression/runner.py -v
"""

import argparse
import difflib
import json
import sys
from pathlib import Path

import pytest

CASES_DIR = Path(__file__).parent / "cases"

STATUS_PASS = "PASS"
STATUS_DEGRADED = "DEGRADED"
STATUS_FAIL = "FAIL"

# 综合质量分阈值
_SCORE_PASS_THRESHOLD = 85
_SCORE_DEGRADED_THRESHOLD = 60


# ---------------------------------------------------------------------------
# 管道运行
# ---------------------------------------------------------------------------


def run_pipeline(input_text: str, import_mode: str | None = None) -> dict:
    """对单个文本 fixture 运行完整 OCR 管道。

    将纯文本包装为 raw_blocks 格式，依次调用:
        normalize → analyze_structure → split_questions → match_answers

    Returns:
        {
            "normalized_blocks": [...],
            "structure": {...},
            "questions": [...],
            "matched": {...},
            "normalized_text": str,   # 全量标准化文本
        }
    """
    from app.features.answer_matcher import match_answers
    from app.features.question_splitter import split_questions
    from app.features.structure_analyzer import analyze_structure
    from app.features.text_normalizer import ImportTextNormalizer

    raw_blocks = [
        {
            "page": 1,
            "block_index": 0,
            "text": input_text,
        }
    ]

    normalizer = ImportTextNormalizer()
    normalized_blocks = normalizer.normalize(raw_blocks)

    structure = analyze_structure(normalized_blocks)

    questions = split_questions(
        normalized_blocks, structure, import_mode=import_mode
    )

    matched = match_answers(questions, normalized_blocks, structure)

    normalized_full_text = "\n".join(
        b["normalized_text"] for b in normalized_blocks
    )

    return {
        "normalized_blocks": normalized_blocks,
        "structure": structure,
        "questions": questions,
        "matched": matched,
        "normalized_text": normalized_full_text,
    }


# ---------------------------------------------------------------------------
# expected.txt 解析与生成
# ---------------------------------------------------------------------------


def _parse_expected(text: str) -> dict:
    """解析 expected.txt 分段格式。

    格式:
        [normalized_full_text]
        <全文标准化文本>
        [/normalized_full_text]
        [questions]
        ---
        number: 1
        stem: ...
        type: single_choice
        options:
          A: ...
          B: ...
        answer: A
        explanation: ...
        option_keys: [A, B, C, D]
        ---
        [/questions]
    """
    result: dict = {
        "combined_text": "",
        "questions": [],
    }

    # 提取标准化全文
    nft_match = _extract_section(text, "normalized_full_text")
    if nft_match is not None:
        result["combined_text"] = nft_match.strip()
    else:
        # 兼容旧格式：整个文件就是全文
        q_section = _extract_section(text, "questions")
        if q_section is not None:
            result["combined_text"] = text.split("[questions]")[0].strip()
        else:
            result["combined_text"] = text.strip()

    # 提取题目列表
    q_section = _extract_section(text, "questions")
    if q_section is not None:
        blocks = q_section.strip().split("---")
        for block in blocks:
            block = block.strip()
            if not block:
                continue
            q = _parse_question_block(block)
            if q:
                result["questions"].append(q)

    return result


def _extract_section(text: str, tag: str) -> str | None:
    """提取 [...tag...]...[/tag] 之间的内容。"""
    start_marker = f"[{tag}]"
    end_marker = f"[/{tag}]"
    start = text.find(start_marker)
    if start == -1:
        return None
    start += len(start_marker)
    end = text.find(end_marker, start)
    if end == -1:
        return text[start:]
    return text[start:end]


def _parse_question_block(block: str) -> dict | None:
    """解析单个题目的 key: value 块。"""
    q: dict = {"options": {}, "option_keys": []}
    in_options = False
    for raw_line in block.split("\n"):
        line = raw_line.strip()
        if not line:
            continue

        if line == "options:":
            in_options = True
            continue

        if in_options:
            if ":" in line and len(line.split(":")[0].strip()) <= 2:
                key, val = line.split(":", 1)
                key = key.strip()
                val = val.strip()
                q["options"][key] = val
                continue
            else:
                in_options = False

        if ":" not in line:
            continue

        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()

        if key == "number":
            q["number"] = int(val)
        elif key == "stem":
            q["stem"] = val
        elif key == "type":
            q["type"] = val
        elif key == "answer":
            q["answer"] = val
        elif key == "explanation":
            q["explanation"] = val
        elif key == "option_keys":
            try:
                q["option_keys"] = json.loads(val)
            except json.JSONDecodeError:
                q["option_keys"] = []

    if "number" not in q:
        return None
    return q


def _build_expected_text(pipeline_result: dict) -> str:
    """从管道输出构建 expected.txt。"""
    lines: list[str] = []
    lines.append("[normalized_full_text]")
    lines.append(pipeline_result["normalized_text"].strip())
    lines.append("[/normalized_full_text]")
    lines.append("")

    matched_by_num: dict[int, dict] = {}
    for m in pipeline_result.get("matched", {}).get("matched", []):
        matched_by_num[m.get("question_number", 0)] = m

    lines.append("[questions]")
    for q in pipeline_result.get("questions", []):
        num = q.get("number", 0)
        matched = matched_by_num.get(num, {})
        lines.append("---")
        lines.append(f"number: {num}")
        lines.append(f"stem: {q.get('raw_question_text', '')}")
        lines.append(
            f"type: {_derive_question_type(q, matched)}"
        )
        lines.append("options:")
        for key, text in q.get("option_lines", {}).items():
            lines.append(f"  {key}: {text}")
        lines.append(
            f"answer: {matched.get('answer', '') or ''}"
        )
        lines.append(
            f"explanation: {matched.get('explanation', '') or ''}"
        )
        opt_keys = sorted(q.get("option_lines", {}).keys())
        lines.append(f"option_keys: {json.dumps(opt_keys)}")
        lines.append("")

    lines.append("[/questions]")
    return "\n".join(lines)


def _derive_question_type(q: dict, matched: dict | None = None) -> str:
    """根据题目结构推导题型。"""
    if q.get("blank_option_groups"):
        return "multi_blank_choice"
    if q.get("has_grouped_options"):
        return "multiple_choice"
    if q.get("has_options") and q.get("option_lines"):
        if len(q.get("option_lines", {})) == 2:
            ans = (matched or {}).get("answer", "")
            if ans in ("T", "F", "正确", "错误"):
                return "true_false"
        return "single_choice"
    return "subjective"


# ---------------------------------------------------------------------------
# 对比与评估
# ---------------------------------------------------------------------------


def compare_output(
    actual: dict, expected_file_text: str, meta: dict
) -> dict:
    """将管道输出与 expected.txt 对比，计算所有指标并分类失败。"""
    expected = _parse_expected(expected_file_text)

    actual_text = actual["normalized_text"]
    actual_questions = actual["questions"]

    expected_text = expected["combined_text"] or expected_file_text.strip()
    expected_questions = expected["questions"]

    ref_lines = [l for l in expected_text.split("\n") if l.strip()]
    hyp_lines = [l for l in actual_text.split("\n") if l.strip()]

    exp_nums = {q.get("number", 0) for q in expected_questions}
    found_nums = {q.get("number", 0) for q in actual_questions}

    exp_opt_keys: dict[int, set[str]] = {}
    for q in expected_questions:
        keys = set(q.get("option_keys", [])) or set(q.get("options", {}).keys())
        exp_opt_keys[q.get("number", 0)] = keys

    found_opt_keys: dict[int, set[str]] = {}
    for q in actual_questions:
        found_opt_keys[q.get("number", 0)] = set(
            q.get("option_lines", {}).keys()
        )

    from tests.ocr_regression.metrics import character_error_rate, ocr_quality_score

    cer = character_error_rate(expected_text, actual_text)
    quality = ocr_quality_score(
        expected_text,
        actual_text,
        exp_nums,
        found_nums,
        exp_opt_keys,
        found_opt_keys,
        ref_lines,
        hyp_lines,
    )

    from tests.ocr_regression.classifier import classify_failures

    exp_opts_full: dict[int, dict[str, str]] = {}
    for q in expected_questions:
        exp_opts_full[q.get("number", 0)] = q.get("options", {})

    found_opts_full: dict[int, dict[str, str]] = {}
    for q in actual_questions:
        found_opts_full[q.get("number", 0)] = q.get("option_lines", {})

    failures = classify_failures(
        expected_text,
        actual_text,
        exp_nums,
        found_nums,
        exp_opts_full,
        found_opts_full,
        actual_questions,
        actual["structure"],
    )

    diff_text = _make_diff(expected_text, actual_text)

    status = _status_from_score(quality["score"])
    known_failures = meta.get("known_failure_types", [])
    if known_failures and status == STATUS_FAIL:
        status = _status_from_known(quality["score"], known_failures, failures)

    return {
        "cer": round(cer, 4),
        "quality": quality,
        "failures": failures,
        "diff": diff_text,
        "question_count": {
            "expected": len(expected_questions),
            "found": len(actual_questions),
        },
        "status": status,
    }


def _make_diff(expected: str, actual: str) -> str:
    """生成 unified diff。"""
    expected_lines = expected.splitlines(keepends=True)
    actual_lines = actual.splitlines(keepends=True)
    diff = difflib.unified_diff(
        expected_lines,
        actual_lines,
        fromfile="expected",
        tofile="actual",
        lineterm="",
    )
    return "".join(diff)


def _status_from_score(score: float) -> str:
    if score >= _SCORE_PASS_THRESHOLD:
        return STATUS_PASS
    if score >= _SCORE_DEGRADED_THRESHOLD:
        return STATUS_DEGRADED
    return STATUS_FAIL


def _status_from_known(
    score: float,
    known_failure_types: list[str],
    failures: list[dict],
) -> str:
    """已知失败类型若完全覆盖实际失败则降级为 DEGRADED。"""
    actual_types = {f["type"] for f in failures}
    known_set = set(known_failure_types)
    if actual_types.issubset(known_set):
        return STATUS_DEGRADED
    return STATUS_FAIL


# ---------------------------------------------------------------------------
# Case 发现与评估
# ---------------------------------------------------------------------------


def discover_cases(case_filter: str | None = None) -> list[Path]:
    """发现所有回归 case 目录。"""
    if not CASES_DIR.exists():
        return []
    cases = sorted(
        d
        for d in CASES_DIR.iterdir()
        if d.is_dir() and (d / "input.txt").exists()
    )
    if case_filter:
        cases = [c for c in cases if c.name.startswith(case_filter)]
    return cases


def evaluate_case(case_dir: Path) -> dict:
    """评估单个回归 case。"""
    input_path = case_dir / "input.txt"
    expected_path = case_dir / "expected.txt"
    meta_path = case_dir / "meta.json"

    if not input_path.exists():
        return {
            "case": case_dir.name,
            "error": "input.txt not found",
        }

    meta = {}
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))

    input_text = input_path.read_text(encoding="utf-8")

    try:
        result = run_pipeline(input_text)
    except Exception as e:
        return {
            "case": case_dir.name,
            "error": f"Pipeline error: {e}",
        }

    if not expected_path.exists():
        return {
            "case": case_dir.name,
            "error": "expected.txt not found (run --baseline to generate)",
            "normalized_text": result["normalized_text"],
            "question_count": len(result["questions"]),
        }

    expected_text = expected_path.read_text(encoding="utf-8")
    comparison = compare_output(result, expected_text, meta)

    return {
        "case": case_dir.name,
        **comparison,
        "meta": meta,
    }


# ---------------------------------------------------------------------------
# 基线生成
# ---------------------------------------------------------------------------


def run_baseline(case_filter: str | None = None) -> list[Path]:
    """从当前管道输出生成 expected.txt 文件。"""
    cases = discover_cases(case_filter)
    updated: list[Path] = []
    for case_dir in cases:
        input_path = case_dir / "input.txt"
        input_text = input_path.read_text(encoding="utf-8")
        result = run_pipeline(input_text)
        expected_text = _build_expected_text(result)
        expected_path = case_dir / "expected.txt"
        expected_path.write_text(expected_text, encoding="utf-8")
        updated.append(case_dir)
        print(f"  Updated baseline: {case_dir.name}")
    return updated


# ---------------------------------------------------------------------------
# 报告输出
# ---------------------------------------------------------------------------


def print_report(results: list[dict], verbose: bool = False) -> None:
    """输出人类可读报告（Task 5 质量基线）。"""
    print("\n" + "=" * 78)
    print("  OCR 回归测试报告")
    print("=" * 78)

    valid = [r for r in results if "error" not in r]
    errors = [r for r in results if "error" in r]

    if not valid:
        print("  无可评估的 case。")
        return

    pass_count = sum(1 for r in valid if r["status"] == STATUS_PASS)
    degraded_count = sum(1 for r in valid if r["status"] == STATUS_DEGRADED)
    fail_count = sum(1 for r in valid if r["status"] == STATUS_FAIL)
    avg_cer = sum(r["cer"] for r in valid) / len(valid)
    avg_score = sum(r["quality"]["score"] for r in valid) / len(valid)

    print(
        f"\n  Cases: {len(valid)} | "
        f"Pass: {pass_count} | "
        f"Degraded: {degraded_count} | "
        f"Fail: {fail_count} | "
        f"Error: {len(errors)}"
    )
    print(
        f"  Avg CER: {avg_cer:.4f} | "
        f"Avg Quality Score: {avg_score:.1f}/100"
    )
    print(
        f"  通过率: {pass_count}/{len(valid)} "
        f"({100 * pass_count / max(len(valid), 1):.0f}%)"
    )

    # 详细表格
    print(f"\n  {'Case':<30} {'CER':>8} {'Score':>7} {'Status':<10} Top Failures")
    print("  " + "-" * 76)
    for r in valid:
        top_f = (
            r["failures"][0]["type"] if r["failures"] else "-"
        )
        print(
            f"  {r['case']:<30} "
            f"{r['cer']:>8.4f} "
            f"{r['quality']['score']:>7.1f} "
            f"{r['status']:<10} "
            f"{top_f}"
        )

    if errors:
        print(f"\n  Errors ({len(errors)}):")
        for r in errors:
            print(f"    {r['case']}: {r['error']}")

    # 失败类型汇总
    failure_counts: dict[str, int] = {}
    failure_confidences: dict[str, list[float]] = {}
    for r in valid:
        for f in r["failures"]:
            t = f["type"]
            failure_counts[t] = failure_counts.get(t, 0) + 1
            failure_confidences.setdefault(t, []).append(f["confidence"])

    if failure_counts:
        print("\n  --- Top 5 失败类型 ---")
        ranked = sorted(failure_counts.items(), key=lambda x: -x[1])
        for i, (ft, count) in enumerate(ranked[:5], 1):
            avg_conf = (
                sum(failure_confidences[ft]) / len(failure_confidences[ft])
            )
            print(f"    {i}. {ft:<12} {count} cases (avg confidence: {avg_conf:.2f})")

    # 模块优化建议
    print("\n  --- 最值得继续优化的模块 ---")
    module_issues: dict[str, list[str]] = _map_failures_to_modules(
        [f for r in valid for f in r["failures"]]
    )
    ranked_modules = sorted(
        module_issues.items(), key=lambda x: -len(x[1])
    )
    for i, (mod, issues) in enumerate(ranked_modules[:5], 1):
        print(f"    {i}. {mod} — 涉及: {', '.join(set(issues))}")

    # 优先级建议
    print("\n  --- 下一阶段优先级建议 ---")
    _print_priority_suggestions(ranked_modules, valid)

    # verbose: 显示失败 diff
    if verbose:
        failed = [r for r in valid if r["status"] != STATUS_PASS]
        if failed:
            print("\n" + "=" * 78)
            print("  失败 Case 详细 Diff")
            print("=" * 78)
            for r in failed:
                print(f"\n  [{r['case']}] CER={r['cer']:.4f} Score={r['quality']['score']:.1f}")
                for f in r["failures"]:
                    print(f"    [{f['type']}] confidence={f['confidence']:.3f}")
                    print(f"    {f['evidence']}")
                if r["diff"]:
                    print("  --- diff ---")
                    for line in r["diff"].split("\n")[:40]:
                        print(f"    {line}")

    print("\n" + "=" * 78 + "\n")


def _map_failures_to_modules(
    failures: list[dict],
) -> dict[str, list[str]]:
    """将失败类型映射到相关模块。"""
    mapping = {
        "题号丢失": "question_splitter",
        "选项错位": "question_splitter._extract_options",
        "公式损坏": "text_normalizer.fix_ocr_formula",
        "两栏串行": "question_splitter._split_merged_two_column",
        "水印污染": "text_normalizer._filter_watermark_text",
        "分页断裂": "question_splitter (cross_page)",
        "表格丢失": "ocr_service (table recognition)",
    }
    result: dict[str, list[str]] = {}
    for f in failures:
        mod = mapping.get(f["type"], "unknown")
        result.setdefault(mod, []).append(f["type"])
    return result


def _print_priority_suggestions(
    ranked_modules: list[tuple[str, list[str]]],
    results: list[dict],
) -> None:
    """根据评估结果输出优先级建议。"""
    fail_count = sum(1 for r in results if r["status"] == STATUS_FAIL)
    degraded_count = sum(1 for r in results if r["status"] == STATUS_DEGRADED)

    if fail_count > 0:
        print(
            f"    P0: 修复 {fail_count} 个 FAIL case — "
            f"主要集中在 {'、'.join(m for m, _ in ranked_modules[:2])}"
        )
    if degraded_count > 0:
        print(
            f"    P1: 提升 {degraded_count} 个 DEGRADED case 至 PASS — "
            f"需改进 {'、'.join(m for m, _ in ranked_modules[:2])}"
        )
    if fail_count == 0 and degraded_count == 0:
        print("    当前基线全部通过，可考虑扩展回归数据集覆盖更多 OCR 失败模式。")

    if ranked_modules:
        top_mod = ranked_modules[0][0]
        print(
            f"    P2: 优先优化 {top_mod}，"
            f"预计影响 {len(ranked_modules[0][1])} 类失败"
        )


def print_json_report(results: list[dict]) -> None:
    """输出 JSON 格式报告。"""
    valid = [r for r in results if "error" not in r]
    summary = {}
    if valid:
        avg_cer = sum(r["cer"] for r in valid) / len(valid)
        avg_score = sum(r["quality"]["score"] for r in valid) / len(valid)
        failure_counts: dict[str, int] = {}
        for r in valid:
            for f in r["failures"]:
                t = f["type"]
                failure_counts[t] = failure_counts.get(t, 0) + 1
        summary = {
            "total_cases": len(valid),
            "pass": sum(1 for r in valid if r["status"] == STATUS_PASS),
            "degraded": sum(1 for r in valid if r["status"] == STATUS_DEGRADED),
            "fail": sum(1 for r in valid if r["status"] == STATUS_FAIL),
            "average_cer": round(avg_cer, 4),
            "average_quality_score": round(avg_score, 1),
            "top_failure_types": sorted(
                failure_counts.items(), key=lambda x: -x[1]
            )[:5],
        }
    output = {"results": results, "summary": summary}
    print(json.dumps(output, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# pytest 集成
# ---------------------------------------------------------------------------


def _case_ids() -> list[str]:
    return [d.name for d in discover_cases()]


@pytest.mark.parametrize("case_name", _case_ids())
def test_ocr_regression(case_name: str):
    """pytest: 每个回归 case 一个参数化测试。"""
    case_dir = CASES_DIR / case_name
    meta_path = case_dir / "meta.json"
    meta = {}
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))

    result = evaluate_case(case_dir)

    if "error" in result:
        if "expected.txt not found" in result["error"]:
            pytest.skip(result["error"])
        pytest.fail(result["error"])

    known_failure_types = meta.get("known_failure_types", [])

    if result["status"] == STATUS_FAIL:
        if known_failure_types:
            failure_names = ", ".join(f["type"] for f in result["failures"])
            pytest.xfail(
                f"[{case_name}] Known failures ({failure_names}): "
                f"CER={result['cer']}, Score={result['quality']['score']}"
            )
        else:
            pytest.fail(
                f"[{case_name}] CER={result['cer']}, "
                f"Score={result['quality']['score']}. "
                f"Failures: {result['failures']}"
            )


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="OCR 回归测试运行器")
    parser.add_argument(
        "--case", type=str, default=None, help="只评测指定 case（前缀匹配）"
    )
    parser.add_argument(
        "--json", action="store_true", help="输出 JSON 格式报告"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="显示失败 diff"
    )
    parser.add_argument(
        "--baseline",
        action="store_true",
        help="从当前管道输出生成/更新 expected.txt",
    )
    args = parser.parse_args()

    if args.baseline:
        print("Generating baseline expected.txt files...")
        updated = run_baseline(args.case)
        if not updated:
            print("No cases updated.", file=sys.stderr)
            sys.exit(1)
        print(f"\nUpdated {len(updated)} baseline files.")
        print("Review them before committing as regression expectations.")
        return

    cases = discover_cases(args.case)
    if not cases:
        print("No regression cases found.", file=sys.stderr)
        print(
            f"Run --baseline first to generate expected.txt files in {CASES_DIR}",
            file=sys.stderr,
        )
        sys.exit(1)

    results = [evaluate_case(c) for c in cases]

    if args.json:
        print_json_report(results)
    else:
        print_report(results, verbose=args.verbose)

    # 有 FAIL 则退出码 1
    if any(
        r.get("status") == STATUS_FAIL
        for r in results
        if "error" not in r
    ):
        sys.exit(1)


if __name__ == "__main__":
    main()
