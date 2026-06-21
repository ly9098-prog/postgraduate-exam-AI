"""OCR 导入告警规则 — 单 pipeline 质量评估。

告警不阻断导入，仅记录到 pipeline status response。
所有字段可选 — 缺字段时不误报。

用法:
    alerts = evaluate_alerts(quality_report, diagnostics)
    # => [{"level": "warning", "code": "high_risk_ratio_too_high", ...}, ...]
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Alert rule definitions
# ---------------------------------------------------------------------------
# Each rule: code, level, condition function (evaluated at runtime).
# `field` is a key path in quality_report/diagnostics (dot-separated).

ALERT_RULES: list[dict[str, Any]] = [
    {
        "code": "import_failed",
        "level": "error",
        "message": "本次导入失败",
        "suggested_action": "检查错误日志，确认文件格式和 OCR 引擎状态",
        # Evaluated via condition function, not field comparison
    },
    {
        "code": "high_risk_ratio_too_high",
        "level": "warning",
        "message": "高风险题比例过高，建议优先人工审核",
        "field": "high_risk_ratio",
        "condition": "gt",
        "threshold": 0.40,
        "suggested_action": "打开高风险筛选，逐题确认",
    },
    {
        "code": "manual_review_rate_too_high",
        "level": "warning",
        "message": "需人工审核的题目比例过高",
        "field": "manual_review_rate",
        "condition": "gt",
        "threshold": 0.50,
        "suggested_action": "检查 PDF 源文件质量，考虑调整 OCR 参数",
    },
    {
        "code": "ai_answer_count_too_high",
        "level": "warning",
        "message": "AI 辅助生成的答案数量过多",
        "field": "ai_answer_count",
        "condition": "gt",
        "threshold": 10,
        "suggested_action": "重点核对 AI 答案的准确性",
    },
    {
        "code": "ocr_cache_hit_rate_too_low",
        "level": "info",
        "message": "OCR 缓存命中率偏低，导入速度可能受影响",
        "field": "ocr_cache_hit_rate",
        "condition": "lt",
        "threshold": 0.20,
        "suggested_action": "如首次导入属正常；如重复导入缓存命中率仍低，检查 OCR_CACHE_DIR 配置",
    },
    {
        "code": "pipeline_duration_too_long",
        "level": "warning",
        "message": "导入耗时过长",
        "field": "duration_ms",
        "condition": "gt",
        "threshold": 300000,  # 5 min
        "suggested_action": "检查源文件页数是否过多或 AI 调用是否异常",
    },
    {
        "code": "ocr_failed_page_ratio_too_high",
        "level": "warning",
        "message": "OCR 解析失败的页面比例过高",
        "field": "ocr_failed_page_ratio",
        "condition": "gt",
        "threshold": 0.30,
        "suggested_action": "检查 PDF 是否为扫描版、图片是否清晰",
    },
]


def evaluate_alerts(
    quality_report: dict | None,
    diagnostics: dict | None,
) -> list[dict]:
    """Evaluate single-pipeline alert rules against pipeline output.

    Args:
        quality_report: from _build_quality_report() output (can be None/empty).
        diagnostics: from _build_diagnostics() output (can be None/empty).

    Returns:
        List of triggered alerts sorted by severity (error → warning → info).
        Empty list = no issues detected.
    """
    qr = quality_report or {}
    diag = diagnostics or {}

    # Compute derived fields from available data
    high_risk_ratio = _safe_ratio(
        qr.get("high_risk"), qr.get("total_questions")
    )
    manual_review_rate = _safe_ratio(
        qr.get("requires_manual_review"), qr.get("total_questions")
    )
    ai_answer_count = qr.get("ai_answer_count", 0) or 0
    duration_ms = (
        (diag.get("performance_profile") or {}).get("_summary") or {}
    ).get("total_duration_ms", 0) or 0
    ocr_cache_hit = qr.get("ocr_cache_hit", 0) or 0
    ocr_cache_miss = qr.get("ocr_cache_miss", 0) or 0
    ocr_cache_hit_rate = _safe_ratio(ocr_cache_hit, ocr_cache_hit + ocr_cache_miss)

    # Count OCR-failed pages from diagnostics
    total_failed_pages = len(set(
        (diag.get("ocr_boxes_failed_pages") or [])
        + (diag.get("ocr_runtime_failed_pages") or [])
    ))
    total_pages = (diag.get("structure") or {}).get("total_pages") or len(
        diag.get("page_classifications") or []
    )
    ocr_failed_page_ratio = _safe_ratio(total_failed_pages, total_pages) if total_pages else 0

    # Field map for rule evaluation
    field_values: dict[str, float | int | str | None] = {
        "high_risk_ratio": high_risk_ratio,
        "manual_review_rate": manual_review_rate,
        "ai_answer_count": ai_answer_count,
        "ocr_cache_hit_rate": ocr_cache_hit_rate,
        "duration_ms": duration_ms,
        "ocr_failed_page_ratio": ocr_failed_page_ratio,
    }

    is_failed = diag.get("status") == "failed" or qr.get("status") == "failed"

    alerts: list[dict] = []

    for rule in ALERT_RULES:
        code = rule["code"]

        if code == "import_failed":
            if is_failed:
                alerts.append(_build_alert(rule, value=None))
            continue

        field_name = rule.get("field")
        if field_name is None:
            continue

        value = field_values.get(field_name)
        if value is None:
            continue  # Missing field → skip (no false alert)

        threshold = rule["threshold"]
        condition = rule.get("condition", "gt")

        triggered = False
        if condition == "gt" and isinstance(value, (int, float)):
            triggered = value > threshold
        elif condition == "lt" and isinstance(value, (int, float)):
            triggered = value < threshold

        if triggered:
            alerts.append(_build_alert(rule, value=value))

    # Sort by severity: error > warning > info
    _severity_order = {"error": 0, "warning": 1, "info": 2}
    alerts.sort(key=lambda a: _severity_order.get(a.get("level", "info"), 99))

    return alerts


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_alert(rule: dict, value: float | int | str | None) -> dict:
    """Build a standardized alert dict from a rule definition."""
    alert: dict[str, Any] = {
        "level": rule["level"],
        "code": rule["code"],
        "message": rule["message"],
    }
    if value is not None:
        alert["value"] = value
    if "threshold" in rule:
        alert["threshold"] = rule["threshold"]
    if "suggested_action" in rule:
        alert["suggested_action"] = rule["suggested_action"]
    return alert


def _safe_ratio(
    numerator: int | float | None, denominator: int | float | None
) -> float:
    """Compute numerator/denominator safely, returning 0 on invalid input."""
    if numerator is None or denominator is None or denominator == 0:
        return 0.0
    return round(numerator / denominator, 4)
