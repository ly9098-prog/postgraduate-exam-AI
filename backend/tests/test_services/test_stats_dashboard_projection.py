"""Compatibility baseline for dashboard-v2 pure response projections."""

from __future__ import annotations

from datetime import date

from app.services.stats_dashboard_projection import (
    build_dashboard_adaptive,
    build_dashboard_growth,
    build_dashboard_overview,
    build_dashboard_review_risk,
    build_dashboard_subjects,
    build_dashboard_trends,
    build_dashboard_yearly_summary,
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


def test_growth_features_recent_unlocks_then_locked_progress():
    growth = build_dashboard_growth(
        {
            "level": 4,
            "level_title": "进阶",
            "level_progress_pct": 37,
            "streak_title": "连续7天",
            "badges": [
                {"key": "u1", "title": "U1", "desc": "D1", "unlocked": True},
                {"key": "l1", "title": "L1", "desc": "D2", "progress": 10},
                {"key": "u2", "title": "U2", "desc": "D3", "unlocked": True},
                {"key": "l2", "title": "L2", "desc": "D4", "progress": 90},
                {"key": "l3", "title": "L3", "desc": "D5", "progress": 50},
            ],
        }
    )

    assert growth["level"] == 4
    assert [badge["key"] for badge in growth["featured_badges"]] == ["u1", "u2", "l2"]
    assert growth["featured_badges"][0]["unlocked"] is True


def test_growth_with_three_unlocked_uses_last_three_in_input_order():
    growth = build_dashboard_growth(
        {
            "badges": [
                {"key": "u1", "title": "U1", "desc": "D1", "unlocked": True},
                {"key": "u2", "title": "U2", "desc": "D2", "unlocked": True},
                {"key": "u3", "title": "U3", "desc": "D3", "unlocked": True},
                {"key": "u4", "title": "U4", "desc": "D4", "unlocked": True},
            ]
        }
    )

    assert [badge["key"] for badge in growth["featured_badges"]] == ["u2", "u3", "u4"]


def test_adaptive_visibility_labels_and_defaults():
    adaptive = build_dashboard_adaptive(
        {
            "interval_status": "fast_forgetting",
            "interval_factor": 0.8,
            "recent_due_recall_rate": 0.4,
            "hard_question_count": 0,
        }
    )
    assert adaptive["visible"] is True
    assert adaptive["interval_status_label"] == "遗忘较快"

    hidden = build_dashboard_adaptive(
        {"interval_factor": 1.0, "hard_question_count": 0}
    )
    assert hidden["visible"] is False
    assert hidden["interval_status"] == "normal"
    assert hidden["interval_status_label"] == "节奏正常"
    assert hidden["target_recall_rate"] == 0.8


def test_yearly_summary_counts_active_days_and_best_day():
    summary = build_dashboard_yearly_summary(
        [
            {"date": "2026-10-01", "questions": 2},
            {"date": "2026-10-02", "questions": 0},
            {"date": "2026-10-03", "questions": 5},
        ]
    )
    assert summary == {
        "active_days": 2,
        "total_questions": 7,
        "best_day_text": "10-03 · 5题",
    }
    assert build_dashboard_yearly_summary([]) == {
        "active_days": 0,
        "total_questions": 0,
        "best_day_text": "暂无记录",
    }
