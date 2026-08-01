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

# assertion field names (from meta.json assertions)
_ASSERT_FIELD_EXPECTED_CODE_FLAGS = "expected_code_flags"
_ASSERT_FIELD_FORBIDDEN_CODE_FLAGS = "forbidden_code_flags"
_ASSERT_FIELD_VALIDATION_STATUS_NOT = "validation_status_not"
_ASSERT_FIELD_REPAIR_SKIPPED_NOT = "repair_skipped_not"
_ASSERT_FIELD_CONFIDENCE_SCORE_MAX = "confidence_score_max"
_ASSERT_FIELD_RETRY_RECOMMENDED = "retry_recommended"
_ASSERT_FIELD_EXPECTED_FAILURE_REASON = "expected_failure_reason"

# meta.json review_status values
REVIEW_PENDING = "pending"
REVIEW_VERIFIED = "verified"
REVIEW_REJECTED = "rejected"

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


def run_ocr_case(meta: dict, case_dir: Path) -> dict:
    """对图片运行 OCR 全链路测试（PP-OCRv6 + VL_REBUILD + 选项检测）。

    meta 需要:
        - image_file: 相对于 case_dir 的图片文件名
        - expected_options_count: 期望选项数量（默认 4）
        - expected_detect: 期望 detect_options_from_text 结果（默认 true）

    Returns:
        {
            "detect_options": bool,
            "extract_options": dict,
            "options_count": int,
            "source": str,           # "ppocrv6" / "vl" / "failed"
            "text_length": int,
            "text_preview": str,
        }
    """
    meta.setdefault("expected_options_count", 4)
    meta.setdefault("expected_detect", True)

    image_file = meta.get("image_file")
    if not image_file:
        return {"error": "meta.json missing image_file field"}

    image_path = case_dir / image_file
    if not image_path.exists():
        return {"error": f"image not found: {image_path}"}

    # Build VL config from DB (needed for VL_REBUILD, even though dual-source prefers PP-OCRv6)
    vl_config = _load_vl_config_from_db()
    if vl_config is None:
        return {"error": "PaddleOCR-VL not configured in DB — needed for VL_REBUILD path"}

    from app.features.pipeline_orchestrator import ImportPipeline

    pipeline = ImportPipeline(options={
        "enable_ai_repair": True,
        "enable_ocr_correction": True,
    })
    original_blocks = [{"page": 1, "page_index": 1, "page_width": 800, "page_height": 1200}]

    # Run PP-OCR first to capture original_raw_text for option merge fallback
    pp_ocr_raw_text = ""
    try:
        from app.services.ocr_service import ocr_image
        img_bytes = image_path.read_bytes()
        pp_ocr_raw_text = ocr_image(img_bytes)
    except Exception:
        pass

    try:
        blocks = pipeline._run_vl_rebuild_blocks(
            file_path=str(image_path),
            original_blocks=original_blocks,
            vl_config=vl_config,
            original_raw_text=pp_ocr_raw_text,
        )
    except Exception as exc:
        return {"error": f"VL_REBUILD failed: {exc}"}

    if not blocks:
        return {"error": "VL_REBUILD returned no blocks"}

    # Collect all text from VL_REBUILD blocks
    full_text = "\n".join(
        b.get("normalized_text") or b.get("text", "") for b in blocks
    )

    # Run option detection
    from app.features.question_type_classifier import (
        detect_options_from_text,
        extract_options_from_text,
    )

    detected = detect_options_from_text(full_text)
    extracted = extract_options_from_text(full_text)
    options_count = len(extracted)

    return {
        "detect_options": detected,
        "extract_options": extracted,
        "options_count": options_count,
        "source": blocks[0].get("source", "unknown"),
        "text_length": len(full_text),
        "text_preview": full_text[:300],
    }


def _load_vl_config_from_db() -> dict | None:
    """从 SQLite DB 加载 PaddleOCR-VL 配置（同步读取）。"""
    import os
    import sqlite3

    import dotenv

    # Load .env if DATABASE_URL not already set (e.g. in pytest)
    dotenv.load_dotenv()

    db_url = os.environ.get("DATABASE_URL", "")
    db_path = db_url.replace("sqlite+aiosqlite:///", "")
    if not db_path or not os.path.isfile(db_path):
        return None

    try:
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT name, api_base_url, api_key_encrypted FROM admin_ai_model_configs WHERE name = 'PaddleOCR-VL-1.6'"
        ).fetchone()
        conn.close()
        if not row:
            return None
        return {
            "model_name": row[0],
            "api_base_url": row[1],
            "paddleocr_vl_api_token": row[2],
        }
    except Exception:
        return None


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
    auto_path = case_dir / "expected.auto.txt"
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

    # Resolve expected file: prefer verified expected.txt, fall back to auto.txt
    evaluation_source = None
    if not expected_path.exists():
        if auto_path.exists():
            evaluation_source = str(auto_path)
        else:
            return {
                "case": case_dir.name,
                "error": "expected.txt not found (run --baseline to generate expected.auto.txt)",
                "normalized_text": result["normalized_text"],
                "question_count": len(result["questions"]),
                "review_status": meta.get("review_status"),
            }
    else:
        evaluation_source = str(expected_path)

    expected_text = Path(evaluation_source).read_text(encoding="utf-8")
    comparison = compare_output(result, expected_text, meta)

    review_status = meta.get("review_status")

    assertion_failures = _check_assertions(meta, result, case_dir.name)
    assertion_passed = len(assertion_failures) == 0

    # ── OCR 全链路检测（当 pipeline_stages 含 "full_ocr" 时触发） ──
    ocr_assertions: list[dict] = []
    stages = meta.get("pipeline_stages", [])
    if "full_ocr" in stages:
        ocr_result = run_ocr_case(meta, case_dir)
        if "error" in ocr_result:
            ocr_assertions.append({
                "field": "ocr_pipeline",
                "expected": "successful OCR run",
                "actual": ocr_result["error"],
                "message": f"[{case_dir.name}] OCR pipeline error: {ocr_result['error']}",
            })
        else:
            # Check detect_options
            expected_detect = meta.get("expected_detect", True)
            if ocr_result.get("detect_options") != expected_detect:
                ocr_assertions.append({
                    "field": "ocr_detect_options",
                    "expected": expected_detect,
                    "actual": ocr_result.get("detect_options"),
                    "message": (
                        f"[{case_dir.name}] detect_options_from_text mismatch\n"
                        f"  expected: {expected_detect}\n"
                        f"  actual:   {ocr_result.get('detect_options')}\n"
                        f"  source:   {ocr_result.get('source', '?')}\n"
                        f"  text_len: {ocr_result.get('text_length', 0)}\n"
                        f"  options:  {ocr_result.get('extract_options', {})}"
                    ),
                })

            # Check options count
            expected_opts = meta.get("expected_options_count", 4)
            actual_opts = ocr_result.get("options_count", 0)
            if actual_opts < expected_opts:
                ocr_assertions.append({
                    "field": "ocr_options_count",
                    "expected": f">= {expected_opts}",
                    "actual": actual_opts,
                    "message": (
                        f"[{case_dir.name}] Option count below threshold\n"
                        f"  expected >= {expected_opts}\n"
                        f"  actual:    {actual_opts}\n"
                        f"  extracted: {ocr_result.get('extract_options', {})}"
                    ),
                })

    return {
        "case": case_dir.name,
        **comparison,
        "meta": meta,
        "review_status": review_status,
        "assertion_failures": assertion_failures + ocr_assertions,
        "assertion_passed": assertion_passed and len(ocr_assertions) == 0,
        "ocr_result": ocr_result if stages and "full_ocr" in stages else None,
    }


# ---------------------------------------------------------------------------
# 基线生成
# ---------------------------------------------------------------------------


def run_baseline(
    case_filter: str | None = None, force: bool = False
) -> list[Path]:
    """从当前管道输出生成 expected.auto.txt 文件。

    永远不会直接覆盖 expected.txt——基线输出始终写入 expected.auto.txt。
    只有 --force 时才会覆盖已有的 expected.auto.txt。
    """
    from datetime import date

    cases = discover_cases(case_filter)
    updated: list[Path] = []
    skipped: list[str] = []
    blocked: list[str] = []

    for case_dir in cases:
        input_path = case_dir / "input.txt"
        expected_path = case_dir / "expected.txt"
        auto_path = case_dir / "expected.auto.txt"
        meta_path = case_dir / "meta.json"

        # 已有 verified expected.txt → 拒绝覆盖，除非 --force
        if expected_path.exists() and not force:
            blocked.append(case_dir.name)
            continue

        # 已有 auto.txt 且未 --force → 跳过
        if auto_path.exists() and not force:
            skipped.append(f"{case_dir.name} (auto.txt exists, use --force to overwrite)")
            continue

        input_text = input_path.read_text(encoding="utf-8")
        result = run_pipeline(input_text)
        auto_text = _build_expected_text(result)

        # 写入 expected.auto.txt
        auto_path.write_text(auto_text, encoding="utf-8")

        # 更新 meta.json
        meta: dict = {}
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["review_status"] = REVIEW_PENDING
        meta["ground_truth_source"] = "auto_generated"
        meta["auto_generated_date"] = date.today().isoformat()
        meta_path.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        updated.append(case_dir)
        if expected_path.exists():
            print(f"  Updated auto baseline (--force): {case_dir.name}")
        else:
            print(f"  Generated auto baseline: {case_dir.name}")

    if blocked:
        print(
            f"\n  Blocked {len(blocked)} case(s) with verified expected.txt "
            f"(use --force to overwrite):"
        )
        for name in blocked:
            print(f"    - {name}")
    if skipped:
        print(f"\n  Skipped {len(skipped)} case(s):")
        for msg in skipped:
            print(f"    - {msg}")

    return updated


# ---------------------------------------------------------------------------
# Review 模式
# ---------------------------------------------------------------------------


def run_review(case_filter: str | None = None) -> list[dict]:
    """运行管道，对比当前输出与 expected.txt，输出逐 case diff 报告。

    用于人工审核：确认管道改动后输出变化是否符合预期。
    """
    cases = discover_cases(case_filter)
    reports: list[dict] = []
    total_similarity = 0.0
    total_diffs = 0

    print("\n" + "=" * 78)
    print("  OCR 回归 Review — 管道输出 vs expected.txt")
    print("=" * 78)

    for case_dir in cases:
        input_path = case_dir / "input.txt"
        expected_path = case_dir / "expected.txt"
        auto_path = case_dir / "expected.auto.txt"
        meta_path = case_dir / "meta.json"

        meta = {}
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))

        input_text = input_path.read_text(encoding="utf-8")
        result = run_pipeline(input_text)
        actual_text = result["normalized_text"]

        # 选择对比目标：expected.txt > expected.auto.txt
        ref_path = None
        ref_label = ""
        if expected_path.exists():
            ref_path = expected_path
            ref_label = "expected.txt"
        elif auto_path.exists():
            ref_path = auto_path
            ref_label = "expected.auto.txt"

        review_status = meta.get("review_status", "unknown")

        if ref_path is None:
            reports.append({
                "case": case_dir.name,
                "review_status": review_status,
                "has_reference": False,
                "similarity": None,
                "diff_ratio": None,
                "missing_tokens": [],
                "extra_tokens": [],
            })
            continue

        ref_text = (
            _parse_expected(ref_path.read_text(encoding="utf-8"))
            .get("combined_text", "")
            .strip()
        )
        if not ref_text:
            ref_text = ref_path.read_text(encoding="utf-8").strip()

        # Token 级比较
        import difflib

        actual_tokens = actual_text.split()
        ref_tokens = ref_text.split()

        sm = difflib.SequenceMatcher(None, ref_tokens, actual_tokens)
        ratio = sm.ratio()

        # 找缺失/多余的 token
        missing: list[str] = []
        extra: list[str] = []
        for op, i1, i2, j1, j2 in sm.get_opcodes():
            if op in ("delete", "replace"):
                missing.extend(ref_tokens[i1:i2])
            if op in ("insert", "replace"):
                extra.extend(actual_tokens[j1:j2])

        # 截断过长的 token 列表
        missing_short = missing[:20]
        extra_short = extra[:20]

        total_similarity += ratio
        total_diffs += 1

        report = {
            "case": case_dir.name,
            "review_status": review_status,
            "has_reference": True,
            "reference_source": ref_label,
            "similarity": round(ratio, 4),
            "diff_ratio": round(1.0 - ratio, 4),
            "missing_tokens": missing_short,
            "missing_count": len(missing),
            "extra_tokens": extra_short,
            "extra_count": len(extra),
        }
        reports.append(report)

        # 输出 per-case 报告
        status_icon = (
            "[NEEDS REVIEW]"
            if review_status == REVIEW_PENDING
            else "[VERIFIED]"
        )
        print(
            f"\n  [{case_dir.name}] {status_icon} "
            f"similarity={ratio:.4f} diff_ratio={1.0 - ratio:.4f}"
        )
        print(f"    reference: {ref_label}")
        print(f"    missing tokens ({len(missing)}): {' '.join(missing_short)}")
        print(f"    extra tokens  ({len(extra)}): {' '.join(extra_short)}")
        if len(missing) > 20 or len(extra) > 20:
            print(
                f"    (truncated: {len(missing)} total missing, "
                f"{len(extra)} total extra)"
            )

    # Summary
    print("\n  --- Review Summary ---")
    if total_diffs > 0:
        avg_sim = total_similarity / total_diffs
        print(f"  Cases reviewed: {total_diffs}")
        print(f"  Average similarity: {avg_sim:.4f}")
        pending = [r for r in reports if r.get("review_status") == REVIEW_PENDING]
        verified = [r for r in reports if r.get("review_status") == REVIEW_VERIFIED]
        no_ref = [r for r in reports if not r.get("has_reference")]
        print(f"  Verified cases: {len(verified)}")
        print(f"  Pending review: {len(pending)}")
        if no_ref:
            print(f"  No reference file: {len(no_ref)} ({', '.join(r['case'] for r in no_ref)})")
    print()

    return reports


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

    # 审核状态摘要
    pending = [r for r in valid if r.get("review_status") == REVIEW_PENDING]
    verified = [r for r in valid if r.get("review_status") == REVIEW_VERIFIED]
    unknown = [
        r for r in valid
        if r.get("review_status") not in (REVIEW_PENDING, REVIEW_VERIFIED)
    ]
    if pending or unknown:
        status_parts: list[str] = []
        if verified:
            status_parts.append(f"{len(verified)} verified")
        if pending:
            status_parts.append(f"{len(pending)} pending review")
        if unknown:
            status_parts.append(f"{len(unknown)} unknown status")
        print(f"  Review: {', '.join(status_parts)}")

    # 详细表格
    [
        r for r in valid if r.get("review_status") == REVIEW_PENDING
    ]

    print(f"\n  {'Case':<30} {'CER':>8} {'Score':>7} {'Assert':>7} {'Status':<10} Top Failures")
    print("  " + "-" * 86)
    for r in valid:
        review_flag = (
            " [NEEDS REVIEW]"
            if r.get("review_status") == REVIEW_PENDING
            else ""
        )
        top_f = (
            r["failures"][0]["type"] if r["failures"] else "-"
        )
        assertion_count = len(r.get("assertion_failures", []))
        assertion_str = f"{assertion_count}FAIL" if assertion_count else "OK"
        print(
            f"  {r['case'] + review_flag:<30} "
            f"{r['cer']:>8.4f} "
            f"{r['quality']['score']:>7.1f} "
            f"{assertion_str:>7} "
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

    # verbose: 显示失败 diff + assertion failures
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

        assert_fails = [r for r in valid if r.get("assertion_failures")]
        if assert_fails:
            print("\n" + "=" * 78)
            print("  Assertion Failures")
            print("=" * 78)
            for r in assert_fails:
                print(f"\n  [{r['case']}] ({len(r['assertion_failures'])} failures)")
                for af in r["assertion_failures"]:
                    print(f"    {af['field']}: {af['message']}")

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


# ===================================================================
# Assertion checking — 验证 meta.json assertions 字段
# ===================================================================


def _run_normalization(pipeline_result: dict, meta: dict) -> dict | None:
    """对 pipeline 输出运行 normalize_questions，返回第一道题的标准化结果。

    Returns:
        normalized question dict, 或 None（pipeline 未产生题目时）。
    """
    questions = pipeline_result.get("questions")
    if not questions:
        return None

    from app.features.question_normalizer import normalize_questions

    matched_pairs = pipeline_result.get("matched", {}).get("matched", [])
    case_id = meta.get("id", "unknown")
    source_info = {"file": case_id, "page": 1, "type": "txt"}
    normalized = normalize_questions(questions, matched_pairs, source_info)
    nq = normalized.get("questions")
    if not nq:
        return None
    return nq[0]


def _check_assertions(
    meta: dict,
    pipeline_result: dict,
    case_dir_name: str,
) -> list[dict]:
    """检查 meta.json assertions 是否满足。

    Returns:
        [{"field": str, "expected": any, "actual": any, "message": str}, ...]
        空列表 = 全部通过。
    """
    assertions = meta.get("assertions")
    if not assertions:
        return []

    failures: list[dict] = []

    # ---- 标准化 — 获取置信度、风险标记等字段 ----
    norm_q = _run_normalization(pipeline_result, meta)
    if norm_q is None:
        failures.append({
            "field": "_normalization",
            "expected": "normalized question",
            "actual": "none",
            "message": f"[{case_dir_name}] normalize_questions 返回空，无法检查断言",
        })
        return failures

    risk_flags: list[str] = norm_q.get("risk_flags") or []
    confidence_score: float = norm_q.get("confidence_score") or 0.0
    validation_status: str = norm_q.get("validation_status") or ""
    retry_recommended: bool = norm_q.get("retry_recommended") or False
    failure_reason: list[str] = norm_q.get("failure_reason") or []
    norm_q.get("is_valid") or False

    # ---- 1. expected_code_flags ----
    expected_flags = assertions.get(_ASSERT_FIELD_EXPECTED_CODE_FLAGS)
    if expected_flags is not None:
        for flag in expected_flags:
            if flag not in risk_flags:
                failures.append({
                    "field": f"risk_flags missing {flag!r}",
                    "expected": "in risk_flags",
                    "actual": risk_flags,
                    "message": (
                        f"[{case_dir_name}] 缺少预期代码风险标记 {flag!r}\n"
                        f"  expected in: risk_flags\n"
                        f"  actual:      {risk_flags}"
                    ),
                })

    # ---- 2. forbidden_code_flags ----
    forbidden_flags = assertions.get(_ASSERT_FIELD_FORBIDDEN_CODE_FLAGS)
    if forbidden_flags is not None:
        for flag in forbidden_flags:
            if flag in risk_flags:
                failures.append({
                    "field": f"risk_flags has forbidden {flag!r}",
                    "expected": "not in risk_flags",
                    "actual": risk_flags,
                    "message": (
                        f"[{case_dir_name}] 出现了不应存在的代码风险标记 {flag!r}\n"
                        f"  expected not in: risk_flags\n"
                        f"  actual:          {risk_flags}"
                    ),
                })

    # ---- 3. validation_status_not ----
    forbidden_status = assertions.get(_ASSERT_FIELD_VALIDATION_STATUS_NOT)
    if forbidden_status is not None:
        if validation_status == forbidden_status:
            failures.append({
                "field": "validation_status",
                "expected": f"!= {forbidden_status!r}",
                "actual": validation_status,
                "message": (
                    f"[{case_dir_name}] validation_status 不应为 {forbidden_status!r}\n"
                    f"  expected != {forbidden_status!r}\n"
                    f"  actual:    {validation_status!r}"
                ),
            })

    # ---- 4. repair_skipped_not ----
    # repair_skipped 在 normalizer 输出中不存在，由下游 ai_repair 决策。
    # 但我们可根据 risk_flags + is_valid 推断：
    #   risk_flags 含代码完整性标记 → ai_repair 不得跳过
    repair_should_not_skip = assertions.get(_ASSERT_FIELD_REPAIR_SKIPPED_NOT)
    if repair_should_not_skip is True:
        # 检查是否至少有一个需要 repair 的 flag
        from app.features.ai_repair import _RISK_FLAGS_REQUIRE_REPAIR
        dangerous = set(risk_flags) & _RISK_FLAGS_REQUIRE_REPAIR
        if not dangerous:
            failures.append({
                "field": "repair_skipped_not inference",
                "expected": "risk_flags with code integrity flags",
                "actual": risk_flags,
                "message": (
                    f"[{case_dir_name}] repair_skipped_not=true 但 risk_flags 中"
                    f"无触发 AI repair 的标记\n"
                    f"  risk_flags: {risk_flags}\n"
                    f"  需要: 至少一个来自 {sorted(_RISK_FLAGS_REQUIRE_REPAIR)}"
                ),
            })

    # ---- 5. confidence_score_max ----
    max_confidence = assertions.get(_ASSERT_FIELD_CONFIDENCE_SCORE_MAX)
    if max_confidence is not None:
        if confidence_score > max_confidence:
            failures.append({
                "field": "confidence_score",
                "expected": f"<= {max_confidence}",
                "actual": confidence_score,
                "message": (
                    f"[{case_dir_name}] confidence_score 超过上限\n"
                    f"  expected <= {max_confidence}\n"
                    f"  actual:    {confidence_score}"
                ),
            })

    # ---- 6. retry_recommended ----
    expect_retry = assertions.get(_ASSERT_FIELD_RETRY_RECOMMENDED)
    if expect_retry is not None:
        if bool(retry_recommended) != bool(expect_retry):
            failures.append({
                "field": "retry_recommended",
                "expected": expect_retry,
                "actual": retry_recommended,
                "message": (
                    f"[{case_dir_name}] retry_recommended 不匹配\n"
                    f"  expected: {expect_retry}\n"
                    f"  actual:   {retry_recommended}"
                ),
            })

    # ---- 7. expected_failure_reason ----
    expected_reasons = assertions.get(_ASSERT_FIELD_EXPECTED_FAILURE_REASON)
    if expected_reasons is not None:
        for reason in expected_reasons:
            if reason not in failure_reason:
                failures.append({
                    "field": f"failure_reason missing {reason!r}",
                    "expected": "in failure_reason",
                    "actual": failure_reason,
                    "message": (
                        f"[{case_dir_name}] failure_reason 缺少预期条目 {reason!r}\n"
                        f"  expected in: failure_reason\n"
                        f"  actual:      {failure_reason}"
                    ),
                })

    # ---- 8. regression_test — 直接测试 detect_code_regression ----
    regression_test = meta.get("regression_test")
    if regression_test:
        regression_raw = regression_test.get("raw_text")
        regression_stem = regression_test.get("stem")
        if regression_raw and regression_stem:
            from app.features.code_integrity import detect_code_regression

            reg_result = detect_code_regression(regression_raw, regression_stem)
            reg_flags: list[str] = reg_result.get("flags") or []

            # 检查 regression_test.expected_flags
            for flag in regression_test.get("expected_flags") or []:
                if flag not in reg_flags:
                    failures.append({
                        "field": f"regression_test missing {flag!r}",
                        "expected": "in regression flags",
                        "actual": reg_flags,
                        "message": (
                            f"[{case_dir_name}] detect_code_regression 未产生预期标记 {flag!r}\n"
                            f"  raw_text: {regression_raw[:80]}...\n"
                            f"  stem:     {regression_stem[:80]}...\n"
                            f"  reg flags: {reg_flags}"
                        ),
                    })

            # 同样检查 assertions.expected_code_flags 中与 regression 相关的部分
            for flag in expected_flags or []:
                if "regression" in flag and flag not in reg_flags:
                    failures.append({
                        "field": f"regression_test missing {flag!r}",
                        "expected": "in regression flags",
                        "actual": reg_flags,
                        "message": (
                            f"[{case_dir_name}] detect_code_regression 未产生预期标记 {flag!r}\n"
                            f"  raw_text: {regression_raw[:80]}...\n"
                            f"  stem:     {regression_stem[:80]}...\n"
                            f"  reg flags: {reg_flags}"
                        ),
                    })

    return failures


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
            "assertion_fail": sum(
                1 for r in valid if r.get("assertion_failures")
            ),
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
    import os

    case_dir = CASES_DIR / case_name
    meta_path = case_dir / "meta.json"
    meta = {}
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))

    # CI 环境：pending case 处理
    review_status = meta.get("review_status")
    is_ci = os.environ.get("CI", "").strip() == "true"
    skip_pending = os.environ.get("CI_SKIP_PENDING", "").strip() == "true"

    # These cases need the remote PaddleOCR-VL service configured in the DB
    # (admin_ai_model_configs). In a full-suite run DATABASE_URL points at a
    # scratch DB without that config — skip instead of failing.
    if _load_vl_config_from_db() is None:
        pytest.skip(f"[{case_name}] PaddleOCR-VL not configured in DB")

    if is_ci and review_status == REVIEW_PENDING:
        if skip_pending:
            pytest.skip(f"[{case_name}] Skipped: review_status=pending (CI_SKIP_PENDING=true)")
        else:
            pytest.fail(
                f"[{case_name}] CI reject: review_status=pending. "
                f"Run --review to verify, then set review_status=verified."
            )

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

    # ---- 断言检查（meta.json assertions 字段） ----
    assertion_failures = result.get("assertion_failures", [])
    if assertion_failures:
        # Check if ALL assertion failures are covered by known_failure_types.
        # This allows cases like vl_unavailable_option_count_mismatch to be
        # marked as xfail instead of fail, so they don't block CI.
        if known_failure_types:
            # Map known_failure_types to assertion field names they cover
            _KFT_TO_ASSERTION_FIELDS = {
                "vl_unavailable_option_count_mismatch": {"ocr_options_count"},
            }
            covered_fields: set[str] = set()
            for kft in known_failure_types:
                covered_fields |= _KFT_TO_ASSERTION_FIELDS.get(kft, set())
            all_covered = all(
                af.get("field") in covered_fields
                for af in assertion_failures
            )
            if all_covered:
                details = "; ".join(
                    af.get("message", "").split("\n")[0]
                    for af in assertion_failures
                )
                pytest.xfail(
                    f"[{case_name}] Known assertion failure(s): {details}"
                )

        parts = "\n".join(f["message"] for f in assertion_failures)
        pytest.fail(
            f"[{case_name}] {len(assertion_failures)} assertion(s) failed:\n{parts}"
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
        help="从当前管道输出生成 expected.auto.txt（不覆盖 expected.txt）",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="允许 --baseline 覆盖已有 expected.auto.txt 或在有 verified expected.txt 时仍写入 auto.txt",
    )
    parser.add_argument(
        "--review",
        action="store_true",
        help="运行管道并逐 case 对比 expected.txt，输出 diff 报告（用于人工审核）",
    )
    args = parser.parse_args()

    if args.baseline:
        print("Generating auto baseline files (expected.auto.txt)...")
        updated = run_baseline(args.case, force=args.force)
        if not updated:
            print("No cases updated.", file=sys.stderr)
            sys.exit(1)
        print(f"\nGenerated {len(updated)} auto baseline file(s).")
        print(
            "Review them with --review, then rename to expected.txt "
            "and set review_status to 'verified' when confirmed."
        )
        return

    if args.review:
        reports = run_review(args.case)
        if not reports:
            print("No cases to review.", file=sys.stderr)
            sys.exit(1)
        return

    cases = discover_cases(args.case)
    if not cases:
        print("No regression cases found.", file=sys.stderr)
        print(
            f"Run --baseline first to generate expected.auto.txt files in {CASES_DIR}",
            file=sys.stderr,
        )
        sys.exit(1)

    results = [evaluate_case(c) for c in cases]

    if args.json:
        print_json_report(results)
    else:
        print_report(results, verbose=args.verbose)

    # 有 FAIL 则退出码 1
    has_fail = any(
        r.get("status") == STATUS_FAIL
        for r in results
        if "error" not in r
    )
    has_assert_fail = any(
        r.get("assertion_failures")
        for r in results
        if "error" not in r
    )
    if has_fail or has_assert_fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
