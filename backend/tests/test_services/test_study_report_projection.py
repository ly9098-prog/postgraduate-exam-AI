"""Compatibility baseline for study-report pure projections."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from app.services.study_report_projection import (
    build_knowledge_mastery_response,
    build_leitner_distribution_response,
    build_overview_response,
    build_review_plan_item,
    build_wrong_question_item,
    calc_priority,
    classify_mastery,
    extract_title,
    mastery_suggestion,
    normalize_study_trend_counts,
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


@dataclass
class KnowledgeRow:
    knowledge_point_id: int
    kp_name: str
    mastery_score: float
    confidence: float
    attempt_count: int
    correct_count: int
    wrong_count: int
    recent_wrong_count: int
    last_practiced_at: datetime | None


@dataclass
class WrongRow:
    question_id: int
    wrong_count: int
    correct_count: int
    answer_count: int
    last_answered_at: datetime | None
    next_review_at: datetime | None
    box_level: int
    q_content: object


@dataclass
class TrendRow:
    d: object
    total: int
    correct: int


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


def test_knowledge_mastery_response_classifies_and_rounds_rows():
    response = build_knowledge_mastery_response(
        [
            KnowledgeRow(1, "weak", 20.04, 0.8, 10, 2, 8, 3, None),
            KnowledgeRow(2, "unknown", 50.0, 0.1, 1, 0, 1, 1, None),
            KnowledgeRow(3, "mastered", 92.0, 0.9, 20, 18, 2, 0, None),
        ]
    )

    assert response["summary"] == {
        "weak_count": 1,
        "normal_count": 0,
        "good_count": 0,
        "mastered_count": 1,
        "unknown_count": 1,
    }
    assert response["items"][0]["mastery_score"] == 20.0
    assert response["items"][0]["confidence"] == 0.8
    assert response["items"][1]["suggestion"].startswith("数据较少")
    assert response["items"][2]["status"] == "mastered"


def test_wrong_question_item_preserves_status_precedence_and_title():
    repeated = build_wrong_question_item(
        row=WrongRow(1, 4, 1, 5, None, None, 0, [{"type": "text", "text": "题干"}]),
        knowledge_point=(7, "操作系统"),
    )
    not_mastered = build_wrong_question_item(
        row=WrongRow(2, 1, 0, 1, None, None, 0, None),
        knowledge_point=None,
    )
    needs_review = build_wrong_question_item(
        row=WrongRow(3, 2, 3, 5, None, None, 2, "普通题干"),
        knowledge_point=None,
    )

    assert repeated["status"] == "repeated_wrong"
    assert repeated["title"] == "题干"
    assert repeated["knowledge_point_name"] == "操作系统"
    assert not_mastered["status"] == "not_mastered"
    assert not_mastered["knowledge_point_id"] is None
    assert needs_review["status"] == "needs_review"
    assert needs_review["title"] == "普通题干"


def test_leitner_distribution_preserves_six_boxes_and_zero_fill():
    response = build_leitner_distribution_response({0: 6, 2: 18, 5: 40})

    assert response["total_tracked_questions"] == 64
    assert [box["box_level"] for box in response["boxes"]] == [0, 1, 2, 3, 4, 5]
    assert response["boxes"][0]["count"] == 6
    assert response["boxes"][0]["label"] == "很不熟"
    assert response["boxes"][1]["count"] == 0
    assert response["boxes"][2]["count"] == 18
    assert response["boxes"][5]["description"] == "长期稳定，偶尔复现"
    assert build_leitner_distribution_response({}) == {
        "boxes": [
            {
                "box_level": level,
                "label": label,
                "description": description,
                "count": 0,
            }
            for level, label, description in [
                (0, "很不熟", "刚做错或反复错误，需要尽快复习"),
                (1, "初步接触", "刚开始掌握，需要短周期复习"),
                (2, "有点熟", "有一定掌握，需要周期复习"),
                (3, "较熟", "掌握较好，保持复习"),
                (4, "熟练", "较稳定掌握，低频复习"),
                (5, "稳定掌握", "长期稳定，偶尔复现"),
            ]
        ],
        "total_tracked_questions": 0,
    }


def test_study_trend_normalizes_dates_and_zero_fills():
    today = date(2026, 10, 22)
    response = normalize_study_trend_counts(
        [
            TrendRow(today.isoformat(), 10, 8),
            TrendRow(today - timedelta(days=2), 5, 3),
            TrendRow("2026-10-21 12:00:00", 4, 4),
            TrendRow(None, 1, 1),
        ],
        today=today,
        days=3,
    )

    assert response["days"] == 3
    assert response["items"] == [
        {
            "date": "2026-10-20",
            "answer_count": 5,
            "correct_count": 3,
            "wrong_count": 2,
            "accuracy": 60.0,
        },
        {
            "date": "2026-10-21",
            "answer_count": 4,
            "correct_count": 4,
            "wrong_count": 0,
            "accuracy": 100.0,
        },
        {
            "date": "2026-10-22",
            "answer_count": 10,
            "correct_count": 8,
            "wrong_count": 2,
            "accuracy": 80.0,
        },
    ]
