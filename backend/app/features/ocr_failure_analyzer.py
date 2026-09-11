"""OCR 导入失败自动归因分析。

兼容 risk_flags 体系，基于 quality_report + diagnostics 输出
失败类型和修复建议，不额外做 I/O。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Failure type definitions
FAILURE_CATEGORIES: dict[str, dict] = {
    "ocr_text_missing": {
        "label": "OCR 文本缺失",
        "suggested_action": "检查源文件质量或 OCR 引擎",
        "severity": "high",
    },
    "question_count_mismatch": {
        "label": "题目数量不符",
        "suggested_action": "检查分段阈值或题号识别",
        "severity": "high",
    },
    "option_count_mismatch": {
        "label": "选项数量不符",
        "suggested_action": "检查选项提取规则或多列排序",
        "severity": "medium",
    },
    "answer_missing": {
        "label": "答案缺失",
        "suggested_action": "人工核对原文答案区域",
        "severity": "high",
    },
    "answer_mismatch": {
        "label": "答案不匹配",
        "suggested_action": "检查答案匹配逻辑",
        "severity": "high",
    },
    "math_formula_uncertain": {
        "label": "数学公式识别不确定",
        "suggested_action": "人工检查公式截图",
        "severity": "medium",
    },
    "math_image_missing": {
        "label": "公式截图缺失",
        "suggested_action": "检查 math_detect 或 PDF 渲染",
        "severity": "medium",
    },
    "code_symbol_changed": {
        "label": "代码符号变更",
        "suggested_action": "检查 code_semantic_guard 结果",
        "severity": "high",
    },
    "table_structure_lost": {
        "label": "表格结构丢失",
        "suggested_action": "检查 table_region_detector 或 Markdown 转换",
        "severity": "medium",
    },
    "multi_column_order_uncertain": {
        "label": "多列顺序不确定",
        "suggested_action": "人工核对阅读顺序",
        "severity": "medium",
    },
    "watermark_noise_remaining": {
        "label": "水印/噪声未清除",
        "suggested_action": "补充水印规则或 text_normalizer 配置",
        "severity": "low",
    },
    "ai_answer_generated": {
        "label": "AI 生成答案",
        "suggested_action": "重点核对 AI 答案是否正确",
        "severity": "medium",
    },
    "ai_modified_sensitive_field": {
        "label": "AI 修改敏感字段",
        "suggested_action": "检查 AI safety gate 日志",
        "severity": "high",
    },
    "resume_duplicate_detected": {
        "label": "断点续传检测到重复",
        "suggested_action": "确认是否为预期重复",
        "severity": "low",
    },
    "artifact_restore_failed": {
        "label": "Artifact 恢复失败",
        "suggested_action": "检查 artifact 文件完整性",
        "severity": "medium",
    },
    "ocr_cache_corrupted": {
        "label": "OCR 缓存损坏",
        "suggested_action": "清除 OCR 缓存后重试",
        "severity": "medium",
    },
}

# risk_flag → failure type mapping (canonical source)
_RISK_FLAG_TO_FAILURE_TYPE: dict[str, str] = {
    "answer_ai_generated": "ai_answer_generated",
    "formula_uncertain": "math_formula_uncertain",
    "math_image_crop_failed": "math_image_missing",
    "code_uncertain": "code_symbol_changed",
    "table_low_confidence": "table_structure_lost",
    "options_anomaly": "option_count_mismatch",
    "answer_missing": "answer_missing",
    "ai_major_edit": "ai_modified_sensitive_field",
    # Secondary mappings (less common but valid)
    "complex_formula_requires_review": "math_formula_uncertain",
    "watermark_noise_detected": "watermark_noise_remaining",
    "garbled_text_detected": "ocr_text_missing",
    "symbol_substitution_detected": "code_symbol_changed",
    "option_structure_corrupted": "option_count_mismatch",
    "semantic_break_detected": "ocr_text_missing",
}


def _make_failure(ftype: str, detail: dict | None = None) -> dict:
    """Build a standardized failure dict from FAILURE_CATEGORIES."""
    cat = FAILURE_CATEGORIES.get(ftype, {})
    result: dict = {
        "type": ftype,
        "label": cat.get("label", ftype),
        "severity": cat.get("severity", "medium"),
        "suggested_action": cat.get("suggested_action", "人工检查"),
    }
    if detail:
        result["detail"] = detail
    return result


def _resolve_severity_order(severity: str) -> int:
    return {"high": 0, "medium": 1, "low": 2}.get(severity, 3)


# ---------------------------------------------------------------------------
# Individual checkers
# ---------------------------------------------------------------------------


def _check_ocr_text_missing(
    quality_report: dict | None,
    diagnostics: dict | None,
) -> list[dict]:
    """Check if OCR produced sufficient text across pages."""
    failures: list[dict] = []
    if not diagnostics:
        return failures

    diag = diagnostics
    failed_boxes = diag.get("ocr_boxes_failed_pages") or []
    fallback_unavailable = diag.get("ocr_text_fallback_unavailable_pages") or []
    runtime_failed = diag.get("ocr_runtime_failed_pages") or []

    total_failed_pages = len(
        set(failed_boxes) | set(fallback_unavailable) | set(runtime_failed)
    )

    if total_failed_pages == 0:
        return failures

    detail: dict[str, Any] = {
        "failed_page_count": total_failed_pages,
    }
    if failed_boxes:
        detail["ocr_boxes_failed_pages"] = list(failed_boxes)
    if fallback_unavailable:
        detail["ocr_text_fallback_unavailable_pages"] = list(fallback_unavailable)
    if runtime_failed:
        detail["ocr_runtime_failed_pages"] = list(runtime_failed)

    failures.append(_make_failure("ocr_text_missing", detail))

    # Also check garbled text from quality report risk distribution
    if quality_report:
        high_risk = quality_report.get("high_risk", 0)
        total = quality_report.get("total_questions", 1)
        if total > 0 and high_risk / total > 0.5:
            # High percentage of high-risk questions may indicate OCR text quality issues
            pass  # Already covered by the page-level check above

    return failures


def _check_question_count(
    quality_report: dict | None,
    expected: dict | None,
) -> list[dict]:
    """Check if question count matches expected range."""
    failures: list[dict] = []
    if not quality_report or not expected:
        return failures

    actual = quality_report.get("total_questions")
    expected_count = expected.get("expected_question_count")
    if actual is None or expected_count is None:
        return failures

    if actual <= 0:
        return failures

    ratio = actual / max(expected_count, 1)

    if ratio < 0.5:
        failures.append(
            _make_failure(
                "question_count_mismatch",
                {
                    "actual": actual,
                    "expected": expected_count,
                    "ratio": round(ratio, 2),
                    "reason": "实际题目数不足预期的 50%，可能存在严重的题号识别或分段问题",
                },
            )
        )
    elif ratio < 0.8:
        # Still flag but with lower urgency context
        failures.append(
            _make_failure(
                "question_count_mismatch",
                {
                    "actual": actual,
                    "expected": expected_count,
                    "ratio": round(ratio, 2),
                    "reason": "实际题目数不足预期的 80%，请确认题号识别和分段阈值",
                },
            )
        )

    # Check for too many questions (oversplitting)
    if ratio > 1.5:
        failures.append(
            _make_failure(
                "question_count_mismatch",
                {
                    "actual": actual,
                    "expected": expected_count,
                    "ratio": round(ratio, 2),
                    "reason": "实际题目数超过预期的 150%，可能存在过度分段",
                },
            )
        )

    return failures


def _check_options(
    quality_report: dict | None,
    diagnostics: dict | None,
) -> list[dict]:
    """Check for option-related anomalies."""
    failures: list[dict] = []
    risk_counts = (diagnostics or {}).get("risk_flag_counts") or {}

    if risk_counts.get("options_anomaly", 0) > 0:
        failures.append(
            _make_failure(
                "option_count_mismatch",
                {
                    "options_anomaly_count": risk_counts["options_anomaly"],
                    "source": "risk_flag_counts",
                },
            )
        )

    if risk_counts.get("option_structure_corrupted", 0) > 0:
        failures.append(
            _make_failure(
                "option_count_mismatch",
                {
                    "option_structure_corrupted_count": risk_counts[
                        "option_structure_corrupted"
                    ],
                    "source": "risk_flag_counts",
                },
            )
        )

    # Check schema_errors for option-related issues
    schema_errors = (diagnostics or {}).get("schema_errors") or []
    option_errors = [
        e
        for e in schema_errors
        if isinstance(e, dict) and "option" in str(e.get("message", "")).lower()
    ]
    if option_errors:
        existing = {f["type"] for f in failures}
        if "option_count_mismatch" not in existing:
            failures.append(
                _make_failure(
                    "option_count_mismatch",
                    {
                        "schema_error_count": len(option_errors),
                        "first_errors": option_errors[:3],
                    },
                )
            )

    return failures


def _check_answers(
    quality_report: dict | None,
    diagnostics: dict | None,
) -> list[dict]:
    """Check for answer-related issues: missing answers and AI-generated answers."""
    failures: list[dict] = []
    risk_counts = (diagnostics or {}).get("risk_flag_counts") or {}

    # AI-generated answers
    ai_answer_count = (quality_report or {}).get("ai_answer_count", 0)
    if ai_answer_count > 0:
        total = (quality_report or {}).get("total_questions", 1) or 1
        failures.append(
            _make_failure(
                "ai_answer_generated",
                {
                    "ai_answer_count": ai_answer_count,
                    "total_questions": total,
                    "ai_answer_rate": round(ai_answer_count / total, 2),
                },
            )
        )

    # Missing answers
    missing = risk_counts.get("answer_missing", 0)
    if missing > 0:
        failures.append(
            _make_failure(
                "answer_missing",
                {
                    "answer_missing_count": missing,
                    "source": "risk_flag_counts",
                },
            )
        )

    # Answer mismatch: if answer_missing rate is high relative to total
    total = (quality_report or {}).get("total_questions", 1) or 1
    if missing > 0 and missing / total > 0.3:
        failures.append(
            _make_failure(
                "answer_mismatch",
                {
                    "answer_missing_ratio": round(missing / total, 2),
                    "reason": "超过 30% 的题目答案缺失，可能答案匹配逻辑有问题",
                },
            )
        )

    return failures


def _check_math(
    quality_report: dict | None,
    diagnostics: dict | None,
    expected: dict | None = None,
) -> list[dict]:
    """Check math formula/image issues."""
    failures: list[dict] = []
    risk_counts = (diagnostics or {}).get("risk_flag_counts") or {}

    # Math formula uncertainty
    if risk_counts.get("formula_uncertain", 0) > 0:
        failures.append(
            _make_failure(
                "math_formula_uncertain",
                {
                    "formula_uncertain_count": risk_counts["formula_uncertain"],
                    "source": "risk_flag_counts",
                },
            )
        )

    if risk_counts.get("complex_formula_requires_review", 0) > 0:
        failures.append(
            _make_failure(
                "math_formula_uncertain",
                {
                    "complex_formula_count": risk_counts[
                        "complex_formula_requires_review"
                    ],
                    "source": "risk_flag_counts",
                },
            )
        )

    # Math image/screenshot missing
    if risk_counts.get("math_image_crop_failed", 0) > 0:
        failures.append(
            _make_failure(
                "math_image_missing",
                {
                    "math_image_crop_failed_count": risk_counts[
                        "math_image_crop_failed"
                    ],
                    "source": "risk_flag_counts",
                },
            )
        )

    # Check if math_image_count is zero but expected non-zero
    math_img_count = (quality_report or {}).get("math_image_count")
    expected_math = (expected or {}).get("expected_math_image_count")
    if expected_math is not None and expected_math > 0:
        if math_img_count is None or math_img_count == 0:
            failures.append(
                _make_failure(
                    "math_image_missing",
                    {
                        "math_image_count": 0,
                        "expected_math_image_count": expected_math,
                        "reason": "预期有数学公式截图但实际为 0",
                    },
                )
            )

    return failures


def _check_tables(
    quality_report: dict | None,
    diagnostics: dict | None,
    expected: dict | None = None,
) -> list[dict]:
    """Check table structure issues."""
    failures: list[dict] = []
    risk_counts = (diagnostics or {}).get("risk_flag_counts") or {}

    if risk_counts.get("table_low_confidence", 0) > 0:
        failures.append(
            _make_failure(
                "table_structure_lost",
                {
                    "table_low_confidence_count": risk_counts["table_low_confidence"],
                    "source": "risk_flag_counts",
                },
            )
        )

    # Prefer the canonical structured-table count while retaining the legacy
    # Markdown metric for old reports.
    table_count = (quality_report or {}).get(
        "table_structured_count",
        (quality_report or {}).get("table_markdown_count", 0),
    )
    expected_tables = (expected or {}).get("expected_table_count")
    if expected_tables is not None and expected_tables > 0:
        if table_count < expected_tables * 0.5:
            failures.append(
                _make_failure(
                    "table_structure_lost",
                    {
                        "table_structured_count": table_count,
                        "expected_table_count": expected_tables,
                        "reason": "实际表格数不足预期的 50%",
                    },
                )
            )

    return failures


def _check_code(
    quality_report: dict | None,
    diagnostics: dict | None,
) -> list[dict]:
    """Check code symbol issues."""
    failures: list[dict] = []
    risk_counts = (diagnostics or {}).get("risk_flag_counts") or {}

    if risk_counts.get("code_uncertain", 0) > 0:
        failures.append(
            _make_failure(
                "code_symbol_changed",
                {
                    "code_uncertain_count": risk_counts["code_uncertain"],
                    "source": "risk_flag_counts",
                },
            )
        )

    # symbol_substitution_detected is also code-related
    if risk_counts.get("symbol_substitution_detected", 0) > 0:
        existing = {f["type"] for f in failures}
        if "code_symbol_changed" not in existing:
            failures.append(
                _make_failure(
                    "code_symbol_changed",
                    {
                        "symbol_substitution_count": risk_counts[
                            "symbol_substitution_detected"
                        ],
                        "source": "risk_flag_counts",
                    },
                )
            )

    return failures


def _check_multi_column(
    quality_report: dict | None,
    diagnostics: dict | None,
) -> list[dict]:
    """Check multi-column reading order issues.

    This detects when layout filters report region signals suggesting
    multi-column layouts that may have uncertain reading order.
    """
    failures: list[dict] = []
    split_diag = (diagnostics or {}).get("split") or {}

    # Check layout_filter region_signals for multi-column indicators
    lf = split_diag.get("layout_filter") or {}
    region_signals = lf.get("region_signals") or []
    multi_col_signals = [
        s
        for s in region_signals
        if isinstance(s, dict)
        and s.get("layout_type") in ("multi_column", "two_column", "split")
    ]
    if multi_col_signals:
        failures.append(
            _make_failure(
                "multi_column_order_uncertain",
                {
                    "multi_column_regions": len(multi_col_signals),
                    "region_previews": [
                        {
                            "page": s.get("page"),
                            "layout_type": s.get("layout_type"),
                        }
                        for s in multi_col_signals[:5]
                    ],
                },
            )
        )

    # Also check structure for multi-column indicators
    structure = (diagnostics or {}).get("structure") or {}
    if (
        structure.get("layout_note")
        and "column" in str(structure["layout_note"]).lower()
    ):
        failures.append(
            _make_failure(
                "multi_column_order_uncertain",
                {
                    "structure_layout_note": structure["layout_note"],
                },
            )
        )

    return failures


def _check_watermark(
    quality_report: dict | None,
    diagnostics: dict | None,
) -> list[dict]:
    """Check watermark/noise remaining issues."""
    failures: list[dict] = []
    risk_counts = (diagnostics or {}).get("risk_flag_counts") or {}

    if risk_counts.get("watermark_noise_detected", 0) > 0:
        failures.append(
            _make_failure(
                "watermark_noise_remaining",
                {
                    "watermark_noise_count": risk_counts["watermark_noise_detected"],
                    "source": "risk_flag_counts",
                },
            )
        )

    # Garbled text from quality gate can also indicate watermark noise
    if risk_counts.get("garbled_text_detected", 0) > 0:
        existing = {f["type"] for f in failures}
        if "watermark_noise_remaining" not in existing:
            failures.append(
                _make_failure(
                    "watermark_noise_remaining",
                    {
                        "garbled_text_count": risk_counts["garbled_text_detected"],
                        "source": "risk_flag_counts",
                        "note": "乱码文本可能与水印/噪声未清除有关",
                    },
                )
            )

    return failures


def _check_ai_intervention(
    quality_report: dict | None,
    diagnostics: dict | None,
) -> list[dict]:
    """Check AI intervention issues: generated answers and safety gate violations."""
    failures: list[dict] = []
    risk_counts = (diagnostics or {}).get("risk_flag_counts") or {}

    # AI major edits (safety gate rejections / sensitive field modifications)
    if risk_counts.get("ai_major_edit", 0) > 0:
        failures.append(
            _make_failure(
                "ai_modified_sensitive_field",
                {
                    "ai_major_edit_count": risk_counts["ai_major_edit"],
                    "source": "risk_flag_counts",
                },
            )
        )

    # Repair stats
    repair_called = (quality_report or {}).get("repair_called", 0)
    repair_skipped = (quality_report or {}).get("repair_skipped", 0)
    if repair_called > 0:
        total = (quality_report or {}).get("total_questions", 1) or 1
        # If repair was called a lot but only for minor issues, add context
        repair_invoked = repair_called + repair_skipped
        if repair_invoked > total * 0.5:
            failures.append(
                _make_failure(
                    "ai_modified_sensitive_field",
                    {
                        "repair_called": repair_called,
                        "repair_skipped": repair_skipped,
                        "repair_rate": round(repair_invoked / total, 2),
                        "reason": "AI repair 调用率过高，可能存在系统性 OCR 问题",
                    },
                )
            )

    # AI answer generation (duplicate check — may be covered by _check_answers)
    qr_ai_count = (quality_report or {}).get("ai_answer_count", 0)
    risk_ai_count = risk_counts.get("answer_ai_generated", 0)
    if qr_ai_count > 0 or risk_ai_count > 0:
        existing = {f["type"] for f in failures}
        if "ai_answer_generated" not in existing:
            failures.append(
                _make_failure(
                    "ai_answer_generated",
                    {
                        "quality_report_ai_count": qr_ai_count,
                        "risk_flag_ai_count": risk_ai_count,
                    },
                )
            )

    return failures


def _check_artifact(
    quality_report: dict | None,
    diagnostics: dict | None,
) -> list[dict]:
    """Check artifact restoration issues."""
    failures: list[dict] = []

    stage_diffs = (diagnostics or {}).get("stage_diffs") or {}
    stage_diffs.get("ai_repair_stats") or {}

    # Artifact restore failure indicators: empty results after resume
    # Look for patterns in diagnostics that suggest artifact issues
    batch_validation = (diagnostics or {}).get("batch_validation") or {}
    if batch_validation.get("artifact_error"):
        failures.append(
            _make_failure(
                "artifact_restore_failed",
                {
                    "artifact_error": batch_validation["artifact_error"],
                },
            )
        )

    # OCR cache corruption: if cache metrics show anomaly
    qr = quality_report or {}
    ocr_cache_hit = qr.get("ocr_cache_hit", 0)
    ocr_cache_miss = qr.get("ocr_cache_miss", 0)
    total_cache = ocr_cache_hit + ocr_cache_miss
    if total_cache > 0:
        # Suspicious pattern: many hits but poor quality
        if (
            ocr_cache_hit > 10
            and qr.get("high_risk", 0) > qr.get("total_questions", 1) * 0.5
        ):
            failures.append(
                _make_failure(
                    "ocr_cache_corrupted",
                    {
                        "ocr_cache_hit": ocr_cache_hit,
                        "ocr_cache_miss": ocr_cache_miss,
                        "high_risk_count": qr.get("high_risk", 0),
                        "reason": "OCR 缓存命中率高但质量差，可能缓存数据已损坏",
                    },
                )
            )

    # Resume duplicate: check review_commit for duplicates
    review_commit = (diagnostics or {}).get("review_commit") or {}
    dupes = review_commit.get("duplicates_filtered", 0)
    if dupes > 0:
        failures.append(
            _make_failure(
                "resume_duplicate_detected",
                {
                    "duplicates_filtered": dupes,
                    "source": "review_commit",
                },
            )
        )

    return failures


# ---------------------------------------------------------------------------
# Main analyzer
# ---------------------------------------------------------------------------


def analyze_failures(
    quality_report: dict | None,
    diagnostics: dict | None,
    expected: dict | None = None,
) -> dict:
    """Analyze pipeline output and classify failures.

    Args:
        quality_report: from _build_quality_report() output.
        diagnostics: from _build_diagnostics() output.
        expected: optional dict with expected metrics
            (e.g. expected_question_count, expected_math_image_count,
             expected_table_count).

    Returns:
        Failure analysis dict:
        {
            "status": "pass" | "warn" | "fail",
            "failures": [
                {
                    "type": "answer_missing",
                    "label": "答案缺失",
                    "severity": "high",
                    "suggested_action": "人工核对原文答案区域",
                    "detail": {...}
                }
            ],
            "failure_type_counts": {"answer_missing": 2, ...},
            "affected_questions": [...],
            "summary": "...",
        }
    """
    qr = quality_report or {}
    diag = diagnostics or {}
    exp = expected or {}

    all_failures: list[dict] = []

    # Run all checkers
    all_failures.extend(_check_ocr_text_missing(qr, diag))
    all_failures.extend(_check_question_count(qr, exp))
    all_failures.extend(_check_options(qr, diag))
    all_failures.extend(_check_answers(qr, diag))
    all_failures.extend(_check_math(qr, diag, exp))
    all_failures.extend(_check_tables(qr, diag, exp))
    all_failures.extend(_check_code(qr, diag))
    all_failures.extend(_check_multi_column(qr, diag))
    all_failures.extend(_check_watermark(qr, diag))
    all_failures.extend(_check_ai_intervention(qr, diag))
    all_failures.extend(_check_artifact(qr, diag))

    # Deduplicate by type (prefer first occurrence with richer detail)
    seen: dict[str, dict] = {}
    for failure in all_failures:
        ftype = failure["type"]
        if ftype not in seen:
            seen[ftype] = failure
        else:
            # Merge details if the new one has more info
            existing_detail = seen[ftype].get("detail") or {}
            new_detail = failure.get("detail") or {}
            if new_detail and not existing_detail:
                seen[ftype]["detail"] = new_detail
            elif new_detail and existing_detail:
                # Merge without overwriting existing keys
                merged = dict(new_detail)
                merged.update(existing_detail)
                seen[ftype]["detail"] = merged

    deduped = list(seen.values())

    # Sort by severity (high first) then by type name
    deduped.sort(key=lambda f: (_resolve_severity_order(f["severity"]), f["type"]))

    # Compute status
    high_count = sum(1 for f in deduped if f["severity"] == "high")
    medium_count = sum(1 for f in deduped if f["severity"] == "medium")
    low_count = sum(1 for f in deduped if f["severity"] == "low")

    if high_count > 0:
        status = "fail"
    elif medium_count > 0:
        status = "warn"
    elif low_count > 0:
        status = "warn"
    else:
        status = "pass"

    # Failure type counts
    failure_type_counts: dict[str, int] = {}
    for f in deduped:
        failure_type_counts[f["type"]] = failure_type_counts.get(f["type"], 0) + 1

    # Extract affected question indices where possible
    affected_questions: list[int] = []
    for f in deduped:
        detail = f.get("detail") or {}
        for key in ("question_indices", "affected_indices"):
            indices = detail.get(key)
            if isinstance(indices, list):
                affected_questions.extend(indices)

    # Build summary
    parts: list[str] = []
    if status == "pass":
        parts.append("导入质量检查通过，未发现明显问题。")
    else:
        fmt = (
            "导入质量检查{}：检测到 {} 个高危、{} 个中危、{} 个低危问题。"
            if status == "fail"
            else "导入质量检查{}：检测到 {} 个中危、{} 个低危问题。"
        )
        warning_word = "未通过" if status == "fail" else "有问题"
        parts.append(fmt.format(warning_word, high_count, medium_count, low_count))

    if deduped:
        top_failures = deduped[:3]
        parts.append("主要问题：" + "；".join(f["label"] for f in top_failures) + "。")

    summary = "".join(parts)

    return {
        "status": status,
        "failures": deduped,
        "failure_type_counts": failure_type_counts,
        "affected_questions": sorted(set(affected_questions))
        if affected_questions
        else [],
        "summary": summary,
    }


def analyze_failures_from_risk_flags(
    risk_flag_counts: dict[str, int] | None,
) -> dict:
    """Lightweight analysis from risk_flag_counts alone (no full diagnostics).

    Useful for quick checks when only risk_flag_counts is available,
    e.g., during acceptance testing or API status endpoints.

    Args:
        risk_flag_counts: dict mapping risk flag names to counts.

    Returns:
        Same shape as analyze_failures() but only uses risk flag data.
    """
    counts = risk_flag_counts or {}
    all_failures: list[dict] = []

    for flag, count in counts.items():
        if count <= 0:
            continue
        ftype = _RISK_FLAG_TO_FAILURE_TYPE.get(flag)
        if ftype:
            all_failures.append(
                _make_failure(
                    ftype,
                    {
                        "risk_flag": flag,
                        "count": count,
                        "source": "risk_flag_counts",
                    },
                )
            )

    # Deduplicate and sort
    seen: dict[str, dict] = {}
    for failure in all_failures:
        ftype = failure["type"]
        if ftype not in seen:
            seen[ftype] = failure
        else:
            # Accumulate counts for same failure type
            existing_detail = seen[ftype].get("detail") or {}
            new_detail = failure.get("detail") or {}
            merged = dict(new_detail)
            merged.update(existing_detail)
            existing_flag = existing_detail.get("risk_flag", "")
            new_flag = new_detail.get("risk_flag", "")
            if existing_flag and new_flag and existing_flag != new_flag:
                merged["risk_flags"] = list(set([existing_flag, new_flag]))
            seen[ftype]["detail"] = merged

    deduped = list(seen.values())
    deduped.sort(key=lambda f: (_resolve_severity_order(f["severity"]), f["type"]))

    high_count = sum(1 for f in deduped if f["severity"] == "high")
    medium_count = sum(1 for f in deduped if f["severity"] == "medium")

    if high_count > 0:
        status = "fail"
    elif medium_count > 0:
        status = "warn"
    elif deduped:
        status = "warn"
    else:
        status = "pass"

    failure_type_counts: dict[str, int] = {}
    for f in deduped:
        failure_type_counts[f["type"]] = failure_type_counts.get(f["type"], 0) + 1

    summary = (
        f"风险标记分析：{len(deduped)} 类问题，高危 {high_count}、中危 {medium_count}。"
        if deduped
        else "风险标记分析：未发现明显问题。"
    )

    return {
        "status": status,
        "failures": deduped,
        "failure_type_counts": failure_type_counts,
        "affected_questions": [],
        "summary": summary,
    }
