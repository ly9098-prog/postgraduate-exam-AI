"""Numeric rules can run without database, ORM, cache or clock fixtures."""

from datetime import date

import pytest

from app.services import dashboard_action_projection as actions
from app.services import dashboard_balance_projection as balance
from app.services import dashboard_quality_projection as quality
from app.services import dashboard_speed_projection as speed
from app.services import dashboard_topic_projection as topics


@pytest.mark.parametrize(("days", "score"), [(0, 100), (1, 100), (2, 59)])
def test_consistency_preserves_out_of_window_rows_and_zero_days(days, score):
    actual = quality.weekly_consistency(
        [("2026-10-30", 10, 8)], date(2026, 10, 30), days
    )
    assert actual["score"] == score
    assert actual["active_days"] == 1
    assert len(actual["day_breakdown"]) == days
    assert actual["total_questions"] == 10


def test_future_rows_count_for_activity_even_when_absent_from_breakdown():
    actual = quality.weekly_consistency([("2026-10-31", 5, 5)], date(2026, 10, 30), 1)
    assert actual["total_questions"] == 5
    assert actual["day_breakdown"] == [
        {"date": "2026-10-30", "questions": 0, "accuracy": 0}
    ]
    assert actual["score"] == 100


@pytest.mark.parametrize(
    ("avg", "expected"), [(None, 0.0), (0, 0.0), (20, 20), (120, 120)]
)
def test_today_missing_and_in_range_time(avg, expected):
    actual = quality.today_quality(20, 20, avg)
    assert actual["score"] == 100 and actual["avg_time_sec"] == expected


def test_fallback_duplicates_and_source_order_are_not_normalized():
    actual = topics.fallback_weak_topics([("same", 2), ("same", None)])
    assert [x["name"] for x in actual["items"]] == ["same", "same"]
    assert [x["mastery_score"] for x in actual["items"]] == [70, 100]


def test_balance_duplicate_groups_last_write_wins_and_non_new_is_review():
    actual = balance.new_vs_review([("new", 10, 0), ("new", 5, 4), ("other", 5, 4)])
    assert actual["new_count"] == actual["review_count"] == 5
    assert actual["label"] == "表现均衡"
    assert actual["summary"] == "新题和复习题表现接近，节奏均衡"


def test_effort_duplicate_subjects_keep_original_total_accumulation():
    actual = balance.input_output([(1, "x", "X", 3, 1, 90), (1, "y", "Y", 3, 3, 30)])
    assert actual["global_avg_time_sec"] == 20
    assert len(actual["items"]) == 1
    assert actual["items"][0]["subject_code"] == "y"
    assert actual["items"][0]["efficiency_score"] == 2


def test_speed_global_and_subject_thresholds_remain_different():
    status = speed.classify_speed(10, 16, 6, 0, 0)
    actual = speed.speed_accuracy(10, 16, 0, 0, status, [(1, "", "", 10, 16, 3)])
    assert actual["overall_status"] == "normal"
    assert actual["by_subject"][0]["status_label"] == "知识点不熟"


def test_actions_preserve_label_substring_precedence_and_missing_field_error():
    actual = actions.action_plan(
        None, None, None, {"label": "复习效果较好新题表现更佳"}
    )
    assert actual["items"][0]["type"] == "practice"
    with pytest.raises(KeyError, match="repeat_rate"):
        actions.action_plan(None, {"is_high": True}, None, None)
