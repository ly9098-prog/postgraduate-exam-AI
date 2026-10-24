"""Compatibility baseline for dashboard-v2 pure response projections."""

from __future__ import annotations

from datetime import date

from app.services.stats_dashboard_projection import (
    build_dashboard_overview,
    build_dashboard_review_risk,
    build_dashboard_subjects,
    build_dashboard_trends,
    previous_trend_start,
)


def test_overview_preserves_accuracy_and_mastery_boundaries():
    overview = {
        "total_questions": 10,
        "total_correct": 6,
        "total_wrong": 4,
        "accuracy": 0.6,
        "today_questions": 3,
        "today_correct": 1,
        "today_duration_sec": 120,
        "consecutive_days": 2,
        "due_review_count": 5,
        "wrong_question_count": 4,
        "mastered_count": 3,
    }
    projected = build_dashboard_overview(overview)

    assert projected["today_accuracy"] == 0.3333
    assert projected["mastery_rate"] == 0.75
    assert projected["mastered_wrong_count"] == 3
    assert build_dashboard_overview(
        {**overview, "today_questions": 0, "today_correct": 0, "wrong_question_count": 0}
    )["today_accuracy"] == 0.0


def test_previous_period_start_is_adjacent_and_non_overlapping():
    today = date(2026, 7, 12)
    start = previous_trend_start(today, 7)

    assert start == date(2026, 6, 29)
    assert start + __import__("datetime").timedelta(days=6) == date(2026, 7, 5)


def test_trends_use_overall_ratio_and_do_not_mutate_points():
    current = [
        {"questions": 2, "correct": 1},
        {"questions": 1, "correct": 0},
    ]
    previous = [{"questions": 3, "correct": 1}]
    before = ([dict(point) for point in current], [dict(point) for point in previous])
    trends = build_dashboard_trends(
        trend_days=2,
        trend_points=current,
        previous_points=previous,
    )

    assert trends["total_questions"] == 3
    assert trends["active_days"] == 2
    assert trends["avg_accuracy"] == 0.3333
    assert trends["previous_total_questions"] == 3
    assert trends["previous_active_days"] == 1
    assert trends["previous_avg_accuracy"] == round(1 / 3, 4)
    assert "近2天累计做题3题" in trends["summary"]
    assert ([dict(point) for point in current], [dict(point) for point in previous]) == before


def test_subjects_preserve_order_and_ties():
    first = {"accuracy": 0.5, "total_questions": 4}
    second = {"accuracy": 0.5, "total_questions": 6}
    subjects = build_dashboard_subjects([first, second])

    assert subjects["items"] == [first, second]
    assert subjects["strongest"] is first
    assert subjects["weakest"] is first
    assert subjects["total_questions"] == 10
    assert build_dashboard_subjects([]) == {
        "items": [],
        "strongest": None,
        "weakest": None,
        "total_questions": 0,
    }


def test_review_risk_limits_topics_and_counts_pseudo_items():
    forgetting = {
        "high_forget_count": 2,
        "stuck_questions": 3,
        "pseudo_mastered": [{}, {}, {}],
        "top_forgotten_topics": ["a", "b", "c", "d", "e", "f"],
    }
    risk = build_dashboard_review_risk(forgetting)

    assert risk["pseudo_mastered_count"] == 3
    assert risk["top_topics"] == ["a", "b", "c", "d", "e"]
