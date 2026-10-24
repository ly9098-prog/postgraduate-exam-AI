"""Pure projections for study-report statistics and recommendations."""

from __future__ import annotations

import json


def safe_accuracy(correct: int, total: int) -> float:
    """Return the historical percentage accuracy with a zero denominator."""
    if total == 0:
        return 0.0
    return round(correct / total * 100, 2)


def extract_title(content_json: object) -> str:
    """Extract the first text segment from question content."""
    if not content_json:
        return ""
    if isinstance(content_json, str):
        stripped = content_json.strip()
        if not (stripped.startswith("[") or stripped.startswith("{")):
            return content_json[:100]
    try:
        content = (
            json.loads(content_json) if isinstance(content_json, str) else content_json
        )
        if isinstance(content, list):
            for segment in content:
                if isinstance(segment, dict) and segment.get("type") == "text":
                    return segment.get("text", "")[:100]
        if isinstance(content, str):
            return content[:100]
    except (json.JSONDecodeError, TypeError):
        pass
    return ""


def classify_mastery(confidence: float, mastery_score: float) -> str:
    """Preserve the historical confidence and mastery thresholds."""
    if confidence < 0.3:
        return "unknown"
    if mastery_score < 40:
        return "weak"
    if mastery_score < 70:
        return "normal"
    if mastery_score < 85:
        return "good"
    return "mastered"


def mastery_suggestion(status: str) -> str:
    """Return the fixed recommendation text for a mastery status."""
    return {
        "weak": "建议优先复习该知识点，并补充同类新题",
        "normal": "建议保持练习，重点关注错题",
        "good": "掌握较好，可以低频复习",
        "mastered": "已较稳定掌握，后续偶尔复现即可",
        "unknown": "数据较少，建议继续练习以提高判断准确度",
    }.get(status, "")


def calc_priority(overdue_days: int, wrong_count: int, box_level: int) -> str:
    """Preserve the historical review-plan priority thresholds."""
    if overdue_days >= 3 or wrong_count >= 3 or box_level <= 1:
        return "high"
    if overdue_days >= 1 or wrong_count >= 1:
        return "medium"
    return "normal"
