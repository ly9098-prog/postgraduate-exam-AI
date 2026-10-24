"""Compatibility baseline for study-report pure projections."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.services.study_report_projection import (
    build_overview_response,
    build_review_plan_item,
    calc_priority,
    classify_mastery,
    extract_title,
    mastery_suggestion,
    safe_accuracy,
)


def test_safe_accuracy_uses_percentage_and_zero_fallback():
    assert safe_accuracy(5, 0) == 0.0
    assert safe_accuracy(10, 10) == 100.0
    assert safe_accuracy(5, 10) == 50.0
    assert safe_accuracy(1, 3) == 33.33


def test_extract_title_preserves_content_shapes_and_100_char_limit():
    assert extract_title(None) == ""
    assert extract_title("短文本") == "短文本"
    assert len(extract_title("A" * 150)) == 100
    assert extract_title('[{"type":"text","text":"题干内容"}]') == "题干内容"
    assert extract_title([{"type": "text", "text": "题干"}]) == "题干"
    assert extract_title([{"type": "image", "url": "x"}]) == ""
    assert extract_title("{invalid") == ""
    assert len(extract_title([{"type": "text", "text": "B" * 150}])) == 100


def test_mastery_classification_and_suggestions_preserve_boundaries():
    assert classify_mastery(0.2, 90) == "unknown"
    assert classify_mastery(0.3, 39) == "weak"
    assert classify_mastery(0.3, 69) == "normal"
    assert classify_mastery(0.3, 84) == "good"
    assert classify_mastery(0.3, 85) == "mastered"
    assert "优先" in mastery_suggestion("weak")
    assert "保持" in mastery_suggestion("normal")
    assert "数据较少" in mastery_suggestion("unknown")
    assert mastery_suggestion("invalid") == ""


def test_priority_preserves_high_medium_normal_thresholds():
    assert calc_priority(3, 0, 3) == "high"
    assert calc_priority(0, 3, 3) == "high"
    assert calc_priority(0, 0, 1) == "high"
    assert calc_priority(1, 0, 3) == "medium"
    assert calc_priority(0, 1, 3) == "medium"
    assert calc_priority(0, 0, 3) == "normal"


def test_overview_response_preserves_accuracy_and_counters():
    response = build_overview_response(
        today_count=2,
        today_correct=1,
        recent_count=3,
        recent_correct=1,
        total_count=10,
        total_correct=7,
        due_count=4,
        overdue_count=2,
        weak_count=3,
        unstable_count=2,
        mastered_count=1,
        wrong_total=5,
        repeated_wrong=2,
    )

    assert response["today_accuracy"] == 50.0
    assert response["recent_accuracy"] == 33.33
    assert response["total_accuracy"] == 70.0
    assert response["weak_knowledge_count"] == 3
    assert response["wrong_question_count"] == 5
    assert build_overview_response(
        today_count=0,
        today_correct=0,
        recent_count=0,
        recent_correct=0,
        total_count=0,
        total_correct=0,
        due_count=0,
        overdue_count=0,
        weak_count=0,
        unstable_count=0,
        mastered_count=0,
        wrong_total=0,
        repeated_wrong=0,
    )["today_accuracy"] == 0.0


@dataclass
class ReviewRow:
    question_id: int
    box_level: int
    wrong_count: int
    correct_count: int
    next_review_at: datetime | None


def test_review_plan_item_projects_overdue_priority_and_knowledge_point():
    now = datetime(2026, 10, 25, 12, 0, 0)
    overdue = build_review_plan_item(
        row=ReviewRow(1, 2, 4, 0, now - timedelta(days=4)),
        knowledge_point=(7, "操作系统"),
        now=now,
    )
    missing = build_review_plan_item(
        row=ReviewRow(2, 3, 0, 1, now - timedelta(hours=12)),
        knowledge_point=None,
        now=now,
    )
    no_time = build_review_plan_item(
        row=ReviewRow(3, 3, 0, 1, None),
        knowledge_point=None,
        now=now,
    )

    assert overdue["overdue_days"] == 4
    assert overdue["priority"] == "high"
    assert overdue["knowledge_point_id"] == 7
    assert overdue["knowledge_point_name"] == "操作系统"
    assert missing["overdue_days"] == 0
    assert missing["priority"] == "normal"
    assert missing["knowledge_point_id"] is None
    assert no_time["overdue_days"] == 0
