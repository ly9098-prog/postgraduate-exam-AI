"""Pure projections for study-report statistics and recommendations."""

from __future__ import annotations

import json
from datetime import timedelta


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


def build_knowledge_mastery_response(rows: list) -> dict:
    """Classify knowledge rows and preserve rounded mastery projections."""
    summary = {
        "weak_count": 0,
        "normal_count": 0,
        "good_count": 0,
        "mastered_count": 0,
        "unknown_count": 0,
    }
    items = []
    for row in rows:
        status = classify_mastery(row.confidence, row.mastery_score)
        summary[f"{status}_count"] = summary.get(f"{status}_count", 0) + 1
        items.append(
            {
                "knowledge_point_id": row.knowledge_point_id,
                "knowledge_point_name": row.kp_name,
                "mastery_score": round(row.mastery_score, 1),
                "confidence": round(row.confidence, 2),
                "answer_count": row.attempt_count,
                "correct_count": row.correct_count,
                "wrong_count": row.wrong_count,
                "recent_wrong_count": row.recent_wrong_count,
                "last_practiced_at": row.last_practiced_at,
                "status": status,
                "suggestion": mastery_suggestion(status),
            }
        )
    return {"summary": summary, "items": items}


def build_wrong_question_item(
    *,
    row: object,
    knowledge_point: tuple[int, str] | None,
) -> dict:
    """Project one wrong-question row and preserve status precedence."""
    if row.wrong_count >= 3:
        status = "repeated_wrong"
    elif row.correct_count == 0:
        status = "not_mastered"
    else:
        status = "needs_review"
    return {
        "question_id": row.question_id,
        "title": extract_title(row.q_content),
        "knowledge_point_id": knowledge_point[0] if knowledge_point else None,
        "knowledge_point_name": knowledge_point[1] if knowledge_point else None,
        "wrong_count": row.wrong_count,
        "correct_count": row.correct_count,
        "answer_count": row.answer_count,
        "last_answered_at": row.last_answered_at,
        "next_review_at": row.next_review_at,
        "box_level": row.box_level,
        "status": status,
    }


def build_leitner_distribution_response(counts: dict) -> dict:
    """Project tracked-question counts into the fixed six-box response."""
    box_meta = (
        (0, "很不熟", "刚做错或反复错误，需要尽快复习"),
        (1, "初步接触", "刚开始掌握，需要短周期复习"),
        (2, "有点熟", "有一定掌握，需要周期复习"),
        (3, "较熟", "掌握较好，保持复习"),
        (4, "熟练", "较稳定掌握，低频复习"),
        (5, "稳定掌握", "长期稳定，偶尔复现"),
    )
    boxes = [
        {
            "box_level": level,
            "label": label,
            "description": description,
            "count": counts.get(level, 0),
        }
        for level, label, description in box_meta
    ]
    return {
        "boxes": boxes,
        "total_tracked_questions": sum(counts.values()),
    }


def normalize_study_trend_counts(
    rows: list,
    *,
    today: object,
    days: int,
) -> dict:
    """Normalize Beijing-date rows and zero-fill the requested day window."""
    data: dict[str, dict[str, int]] = {}
    for row in rows:
        raw = row.d
        try:
            date_text = raw[:10] if isinstance(raw, str) else raw.isoformat()
        except (AttributeError, TypeError):
            date_text = str(raw)[:10]
        data[date_text] = {"total": int(row.total), "correct": int(row.correct)}

    items = []
    for offset in range(days):
        day = today - timedelta(days=days - 1 - offset)
        date_text = day.isoformat()
        entry = data.get(date_text, {"total": 0, "correct": 0})
        total = entry["total"]
        correct = entry["correct"]
        items.append(
            {
                "date": date_text,
                "answer_count": total,
                "correct_count": correct,
                "wrong_count": total - correct,
                "accuracy": safe_accuracy(correct, total),
            }
        )
    return {"days": days, "items": items}
