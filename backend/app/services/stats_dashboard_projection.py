"""Pure projections for the user learning dashboard response."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any


def build_dashboard_overview(overview: dict[str, Any]) -> dict[str, Any]:
    """Project aggregate counters into the dashboard overview shape."""
    wrong_count = overview.get("wrong_question_count", 0)
    mastered_count = overview.get("mastered_count", 0)
    today_questions = overview["today_questions"]
    return {
        "total_questions": overview["total_questions"],
        "total_correct": overview["total_correct"],
        "total_wrong": overview["total_wrong"],
        "accuracy": overview["accuracy"],
        "today_questions": today_questions,
        "today_correct": overview["today_correct"],
        "today_accuracy": round(
            overview["today_correct"] / max(1, today_questions), 4
        )
        if today_questions > 0
        else 0.0,
        "today_duration_sec": overview["today_duration_sec"],
        "consecutive_days": overview["consecutive_days"],
        "due_review_count": overview["due_review_count"],
        "wrong_question_count": wrong_count,
        "mastered_wrong_count": mastered_count,
        "mastery_rate": round(mastered_count / wrong_count, 4)
        if wrong_count > 0
        else 0.0,
    }


def previous_trend_start(today: date, trend_days: int) -> date:
    """Return the adjacent, non-overlapping previous-period start."""
    return today - timedelta(days=2 * trend_days - 1)


def build_dashboard_trends(
    *,
    trend_days: int,
    trend_points: list[dict[str, Any]],
    previous_points: list[dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate current and previous trend points without mutating inputs."""
    trend_total = sum(point.get("questions", 0) for point in trend_points)
    trend_correct = sum(point.get("correct", 0) for point in trend_points)
    trend_active = sum(1 for point in trend_points if point.get("questions", 0) > 0)
    trend_avg_acc = round(trend_correct / trend_total, 4) if trend_total > 0 else 0.0

    prev_total = sum(point.get("questions", 0) for point in previous_points)
    prev_correct = sum(point.get("correct", 0) for point in previous_points)
    prev_active = sum(1 for point in previous_points if point.get("questions", 0) > 0)
    prev_avg_acc = round(prev_correct / prev_total, 4) if prev_total > 0 else 0.0

    return {
        "days": trend_days,
        "points": trend_points,
        "previous_points": previous_points,
        "total_questions": trend_total,
        "active_days": trend_active,
        "avg_accuracy": trend_avg_acc,
        "previous_total_questions": prev_total,
        "previous_active_days": prev_active,
        "previous_avg_accuracy": prev_avg_acc,
        "summary": (
            f"近{trend_days}天累计做题{trend_total}题，"
            f"平均正确率{round(trend_avg_acc * 100)}%，活跃{trend_active}天。"
        ),
    }


def build_dashboard_subjects(subject_items: list[dict[str, Any]]) -> dict[str, Any]:
    """Project subject rows and preserve min/max tie behavior."""
    strongest = max(subject_items, key=lambda item: item["accuracy"]) if subject_items else None
    weakest = min(subject_items, key=lambda item: item["accuracy"]) if subject_items else None
    return {
        "items": subject_items,
        "strongest": strongest,
        "weakest": weakest,
        "total_questions": sum(item.get("total_questions", 0) for item in subject_items),
    }


def build_dashboard_review_risk(forgetting_data: dict[str, Any]) -> dict[str, Any]:
    """Project forgetting diagnostics into the dashboard risk section."""
    pseudo_count = len(forgetting_data.get("pseudo_mastered", []))
    return {
        "high_forget_count": forgetting_data.get("high_forget_count", 0),
        "stuck_questions": forgetting_data.get("stuck_questions", 0),
        "pseudo_mastered_count": pseudo_count,
        "top_topics": forgetting_data.get("top_forgotten_topics", [])[:5],
    }
