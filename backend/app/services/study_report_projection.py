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


def build_overview_response(
    *,
    today_count: int,
    today_correct: int,
    recent_count: int,
    recent_correct: int,
    total_count: int,
    total_correct: int,
    due_count: int,
    overdue_count: int,
    weak_count: int,
    unstable_count: int,
    mastered_count: int,
    wrong_total: int,
    repeated_wrong: int,
) -> dict:
    """Project overview counters while preserving percentage accuracy."""
    return {
        "today_answer_count": today_count,
        "today_correct_count": today_correct,
        "today_accuracy": safe_accuracy(today_correct, today_count),
        "recent_answer_count": recent_count,
        "recent_correct_count": recent_correct,
        "recent_accuracy": safe_accuracy(recent_correct, recent_count),
        "total_answer_count": total_count,
        "total_correct_count": total_correct,
        "total_accuracy": safe_accuracy(total_correct, total_count),
        "due_review_count": due_count,
        "overdue_review_count": overdue_count,
        "weak_knowledge_count": weak_count,
        "unstable_knowledge_count": unstable_count,
        "mastered_knowledge_count": mastered_count,
        "wrong_question_count": wrong_total,
        "repeated_wrong_question_count": repeated_wrong,
    }


def build_review_plan_item(
    *,
    row: object,
    knowledge_point: tuple[int, str] | None,
    now: object,
) -> dict:
    """Project one due question row and preserve overdue/priority rules."""
    overdue_days = (
        max(0, int((now - row.next_review_at).total_seconds() // 86400))
        if row.next_review_at
        else 0
    )
    return {
        "question_id": row.question_id,
        "knowledge_point_id": knowledge_point[0] if knowledge_point else None,
        "knowledge_point_name": knowledge_point[1] if knowledge_point else None,
        "box_level": row.box_level,
        "wrong_count": row.wrong_count,
        "correct_count": row.correct_count,
        "next_review_at": row.next_review_at,
        "overdue_days": overdue_days,
        "priority": calc_priority(overdue_days, row.wrong_count, row.box_level),
    }
