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


def build_dashboard_growth(growth: dict[str, Any]) -> dict[str, Any]:
    """Project the growth profile and prioritize recently unlocked badges."""
    badges = growth.get("badges", [])
    unlocked = [badge for badge in badges if badge.get("unlocked")]
    locked_sorted = sorted(
        [badge for badge in badges if not badge.get("unlocked")],
        key=lambda badge: badge.get("progress", 0),
        reverse=True,
    )
    featured = (
        unlocked[-3:]
        if len(unlocked) >= 3
        else unlocked + locked_sorted[: 3 - len(unlocked)]
    )[:3]
    return {
        "level": growth.get("level", 1),
        "level_title": growth.get("level_title", ""),
        "level_progress_pct": growth.get("level_progress_pct", 0),
        "streak_title": growth.get("streak_title", ""),
        "featured_badges": [
            {
                "key": badge["key"],
                "title": badge["title"],
                "desc": badge["desc"],
                "unlocked": badge.get("unlocked", False),
                "progress_text": badge.get("progress_text", ""),
            }
            for badge in featured
        ],
    }


def build_dashboard_adaptive(adaptive: dict[str, Any]) -> dict[str, Any]:
    """Project adaptive-learning state and preserve the normal fallback."""
    status_map = {
        "fast_forgetting": "遗忘较快",
        "slightly_fast_forgetting": "略偏快遗忘",
        "normal": "节奏正常",
        "stable_memory": "记忆稳定",
    }
    status = adaptive.get("interval_status", "normal")
    recall_rate = adaptive.get("recent_due_recall_rate", 0)
    target = adaptive.get("target_recall_rate", 0.8)
    return {
        "visible": (adaptive.get("interval_factor") != 1.0)
        or (adaptive.get("hard_question_count", 0) > 0),
        "interval_status": status,
        "interval_status_label": status_map.get(status, "节奏正常"),
        "recent_due_recall_rate": recall_rate,
        "target_recall_rate": target,
    }


def build_dashboard_yearly_summary(yearly_trends: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate the 365-day trend into the compact yearly card."""
    active_days = sum(1 for point in yearly_trends if point.get("questions", 0) > 0)
    total_questions = sum(point.get("questions", 0) for point in yearly_trends)
    best = (
        max(yearly_trends, key=lambda point: point.get("questions", 0))
        if yearly_trends
        else {}
    )
    best_text = (
        f"{best.get('date', '')[-5:]} · {best.get('questions', 0)}题"
        if best.get("questions", 0)
        else "暂无记录"
    )
    return {
        "active_days": active_days,
        "total_questions": total_questions,
        "best_day_text": best_text,
    }
