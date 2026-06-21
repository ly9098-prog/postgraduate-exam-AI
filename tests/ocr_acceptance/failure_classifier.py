"""Acceptance test failure classifier.

Wraps ocr_failure_analyzer for acceptance test reports.
Compares actual output against case.json expected values.
"""

from __future__ import annotations

import sys
from typing import Any

# Ensure backend is importable
try:
    from app.features.ocr_failure_analyzer import (
        analyze_failures,
        analyze_failures_from_risk_flags,
        FAILURE_CATEGORIES,
    )
except ImportError:
    # Allow running from tests/ directory without full backend setup
    import os as _os

    _backend_root = _os.path.join(_os.path.dirname(__file__), "..", "..", "backend")
    sys.path.insert(0, _backend_root)
    from app.features.ocr_failure_analyzer import (
        analyze_failures,
        analyze_failures_from_risk_flags,
        FAILURE_CATEGORIES,
    )


def classify_acceptance_result(
    case_meta: dict | None,
    pipeline_output: dict | None,
    acceptance_metrics: dict | None,
) -> dict:
    """Classify acceptance case result using expected metrics from case.json.

    Compares the pipeline's quality_report and diagnostics against the
    expected values declared in case.json (case_meta).

    Args:
        case_meta: Dict from case.json with fields like
            expected_question_count, expected_answer_count,
            expected_math_image_count, expected_table_count,
            expected_code_blocks, known_risks.
        pipeline_output: Optional dict containing quality_report and
            diagnostics from the import pipeline.
        acceptance_metrics: Optional dict of metric measurements
            (question_count_recall, option_integrity, etc.).

    Returns:
        {
            "status": "pass" | "warn" | "fail",
            "failure_analysis": {...},
            "metric_gaps": [...],
            "known_risks_matched": [...],
            "recommendation": "...",
        }
    """
    meta = case_meta or {}
    output = pipeline_output or {}
    metrics = acceptance_metrics or {}

    # Extract quality_report and diagnostics from pipeline output
    quality_report = output.get("quality_report")
    diagnostics = output.get("diagnostics")

    # Build expected dict from case_meta
    expected: dict[str, Any] = {}
    for key in (
        "expected_question_count",
        "expected_answer_count",
        "expected_math_image_count",
        "expected_table_count",
    ):
        val = meta.get(key)
        if val is not None:
            expected[key] = val
    if meta.get("expected_code_blocks") is not None:
        expected["expected_code_blocks"] = meta["expected_code_blocks"]

    # Run failure analysis
    failure_analysis = analyze_failures(quality_report, diagnostics, expected)

    # Compare acceptance metrics against expected values
    metric_gaps: list[dict] = _compute_metric_gaps(metrics, expected, meta)

    # Match detected failures against known_risks from case.json
    known_risks_matched: list[dict] = _match_known_risks(
        failure_analysis.get("failures", []),
        meta.get("known_risks", []),
    )

    # Determine overall status
    analysis_status = failure_analysis.get("status", "pass")
    gap_has_critical = any(
        g.get("severity") == "critical" for g in metric_gaps
    )

    if analysis_status == "fail" or gap_has_critical:
        overall = "fail"
    elif analysis_status == "warn" or metric_gaps:
        overall = "warn"
    else:
        overall = "pass"

    # Build recommendation
    recommendation = _build_recommendation(
        overall,
        failure_analysis,
        metric_gaps,
        known_risks_matched,
    )

    result: dict[str, Any] = {
        "status": overall,
        "failure_analysis": failure_analysis,
    }
    if metric_gaps:
        result["metric_gaps"] = metric_gaps
    if known_risks_matched:
        result["known_risks_matched"] = known_risks_matched
    result["recommendation"] = recommendation

    # If we have risk_flag_counts but no full diagnostics, add lightweight analysis
    risk_counts = (diagnostics or {}).get("risk_flag_counts")
    if risk_counts and not quality_report:
        risk_analysis = analyze_failures_from_risk_flags(risk_counts)
        result["risk_flag_analysis"] = risk_analysis

    return result


def _compute_metric_gaps(
    metrics: dict,
    expected: dict,
    case_meta: dict,
) -> list[dict]:
    """Compare measured metrics against case.json expectations.

    Returns list of gap dicts with severity, actual, expected, and detail.
    """
    gaps: list[dict] = []

    # Map case_meta keys to metrics keys
    comparisons = [
        ("expected_question_count", "question_count_recall", "question_count", "题目数量"),
        ("expected_answer_count", "answer_match_rate", "answer_count", "答案匹配率"),
        ("expected_math_image_count", "math_image_presence", "math_image_count", "数学公式截图"),
        ("expected_table_count", "table_structure_presence", "table_count", "表格结构"),
    ]

    for expected_key, metric_key, display_name, label in comparisons:
        expected_val = expected.get(expected_key)
        if expected_val is None:
            continue
        actual_val = metrics.get(metric_key)
        if actual_val is None:
            continue

        if isinstance(actual_val, (int, float)) and actual_val < 0.3:
            gaps.append({
                "metric": display_name,
                "label": label,
                "expected": expected_val,
                "actual": actual_val,
                "severity": "critical",
                "detail": f"{label}实际值({actual_val})远低于预期",
            })
        elif isinstance(actual_val, (int, float)) and actual_val < 0.7:
            gaps.append({
                "metric": display_name,
                "label": label,
                "expected": expected_val,
                "actual": actual_val,
                "severity": "warning",
                "detail": f"{label}实际值({actual_val})偏低",
            })

    # Check code symbol preservation if expected_code_blocks provided
    code_preservation = metrics.get("code_symbol_preservation")
    expected_code = expected.get("expected_code_blocks")
    if code_preservation is not None and expected_code is not None and expected_code > 0:
        if code_preservation < 0.8:
            gaps.append({
                "metric": "code_symbol_preservation",
                "label": "代码符号保留",
                "expected": expected_code,
                "actual": code_preservation,
                "severity": "critical" if code_preservation < 0.5 else "warning",
                "detail": f"代码符号保留率({code_preservation})低于阈值",
            })

    # Manual review rate check
    manual_review = metrics.get("manual_review_rate")
    if manual_review is not None and manual_review > 0.5:
        gaps.append({
            "metric": "manual_review_rate",
            "label": "需人工审核率",
            "expected": "<0.30",
            "actual": manual_review,
            "severity": "warning",
            "detail": f"需人工审核的题目比例过高({manual_review:.0%})",
        })

    return gaps


def _match_known_risks(
    failures: list[dict],
    known_risks: list[str],
) -> list[dict]:
    """Match detected failures against known_risks from case.json.

    Returns list with match status for each known risk.
    """
    if not known_risks:
        return []

    failure_labels = {f.get("label", "") for f in failures}
    failure_types = {f.get("type", "") for f in failures}

    matched: list[dict] = []
    for risk in known_risks:
        risk_lower = risk.lower()
        is_detected = False
        detected_by = []

        # Check against failure labels
        for f in failures:
            label = f.get("label", "")
            detail = f.get("detail") or {}
            # Simple keyword matching
            keywords = _extract_keywords(risk)
            if any(kw in label or kw in str(detail) for kw in keywords):
                is_detected = True
                detected_by.append(f["type"])

        matched.append({
            "risk": risk,
            "detected": is_detected,
            "matched_failure_types": detected_by if detected_by else None,
        })

    return matched


def _extract_keywords(risk_text: str) -> list[str]:
    """Extract key Chinese/English words from a risk description."""
    # Simple extraction: split and keep significant tokens
    words = risk_text.replace("，", " ").replace("、", " ").split()
    # Filter very short words
    keywords = [w for w in words if len(w) >= 2]
    return keywords[:6]  # Keep top N


def _build_recommendation(
    status: str,
    failure_analysis: dict,
    metric_gaps: list[dict],
    known_risks_matched: list[dict],
) -> str:
    """Build a human-readable recommendation based on analysis results."""
    parts: list[str] = []

    if status == "pass":
        return "验收通过：导入质量符合预期，可进入下一阶段。"

    # Failure-based recommendations
    failures = failure_analysis.get("failures", [])
    high_failures = [f for f in failures if f.get("severity") == "high"]
    medium_failures = [f for f in failures if f.get("severity") == "medium"]

    if high_failures:
        actions = [f.get("suggested_action", "") for f in high_failures]
        parts.append(f"高危问题需优先处理：{'；'.join(actions[:3])}。")

    if metric_gaps:
        critical_gaps = [g for g in metric_gaps if g.get("severity") == "critical"]
        if critical_gaps:
            gap_labels = [g["label"] for g in critical_gaps]
            parts.append(f"关键指标严重偏离：{'、'.join(gap_labels)}。")

    # Check if all failures are known risks (acceptable if documented)
    undetected_risks = [r for r in known_risks_matched if not r.get("detected")]
    if undetected_risks and not high_failures:
        parts.append("已知风险未实际触发，可考虑收紧检测阈值。")

    if not parts:
        parts.append("存在中低危问题，建议人工抽查确认。")

    return "".join(parts)
