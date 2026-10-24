"""Compatibility baseline for learning-AI provider payload normalization."""

from __future__ import annotations

from datetime import datetime

from app.services.stats_ai_projection import (
    build_dashboard_ai_payload,
    build_dashboard_ai_prompt,
    build_dashboard_ai_response,
    build_rule_based_dashboard_analysis,
    build_knowledge_point_stats,
    build_local_ai_diagnosis,
    normalize_knowledge_points,
)


def test_knowledge_points_require_string_names_and_bound_text():
    points = normalize_knowledge_points(
        [
            {"knowledge_point": " 数据结构 ", "accuracy": 0.8, "suggestion": " 保持 "},
            {"knowledge_point": 123},
            {"knowledge_point": "   "},
            {"knowledge_point": "网络", "suggestion": 123},
        ],
        limit=5,
    )

    assert points == [
        {
            "knowledge_point": "数据结构",
            "accuracy": 0.8,
            "suggestion": "保持",
        },
        {"knowledge_point": "网络", "accuracy": 0.0, "suggestion": ""},
    ]


def test_knowledge_points_clamp_accuracy_and_preserve_limits():
    points = normalize_knowledge_points(
        [
            {"knowledge_point": "a", "accuracy": 80},
            {"knowledge_point": "b", "accuracy": "bad"},
            {"knowledge_point": "c", "accuracy": -1},
            {"knowledge_point": "d", "accuracy": 2},
            {"knowledge_point": "e", "accuracy": 1},
        ],
        limit=3,
    )

    assert [point["knowledge_point"] for point in points] == ["a", "b", "c"]
    assert [point["accuracy"] for point in points] == [0.8, 0.0, 0.0]
    assert all(len(point["knowledge_point"]) <= 80 for point in points)


def test_dashboard_ai_payload_is_bounded_and_uses_overall_trend_ratio():
    payload = build_dashboard_ai_payload(
        overview={
            "today_questions": 2,
            "today_correct": 1,
            "due_review_count": 3,
            "consecutive_days": 4,
            "total_questions": 10,
            "accuracy": 0.6,
        },
        subject_items=[
            {"label": "A", "accuracy": 0.8, "total_questions": 6},
            {"label": "B", "accuracy": 0.4, "total_questions": 4},
            {"label": "C", "accuracy": 0.5, "total_questions": 2},
        ],
        trends=[
            {"questions": 2, "correct": 1},
            {"questions": 1, "correct": 0},
        ],
        forgetting={
            "high_forget_count": 2,
            "stuck_questions": 1,
            "top_forgotten_topics": [{"topic": f"t{i}"} for i in range(6)],
        },
        trend_days=2,
    )

    assert payload["overview"]["today_accuracy"] == 0.5
    assert payload["trends"]["avg_accuracy"] == round(1 / 3, 4)
    assert payload["subjects"]["strongest"] == "A"
    assert payload["subjects"]["weakest"] == "B"
    assert len(payload["subjects"]["items"]) == 3
    assert len(payload["review_risk"]["top_topics"]) == 5


def test_dashboard_ai_response_normalizes_and_rejects_empty_payload():
    response = build_dashboard_ai_response(
        parsed={
            "summary": " x " + "y" * 320,
            "findings": ["a", 1, "b"],
            "risks": ["r"],
            "actions": [
                {"type": "REVIEW", "title": "复习", "desc": "先复习"},
                {"type": "bad", "title": "bad"},
            ],
        },
        ai_response={"model": "model-a"},
        generated_at="2026-10-25T10:00:00Z",
    )

    assert response is not None
    assert len(response["summary"]) == 320
    assert response["findings"] == ["a", "b"]
    assert response["actions"][0]["type"] == "review"
    assert response["model"] == "model-a"
    assert response["generated"] is True
    assert build_dashboard_ai_response(
        parsed={"summary": 1, "findings": [], "risks": [], "actions": []},
        ai_response={"model": "model-a"},
        generated_at="now",
    ) is None


def test_dashboard_ai_prompt_contains_json_contract_and_payload():
    payload = {"overview": {"total_questions": 1}}
    messages = build_dashboard_ai_prompt(payload, trend_days=7)

    assert messages[0]["role"] == "system"
    assert '"summary"' in messages[0]["content"]
    assert "review|wrong|practice|subject" in messages[0]["content"]
    assert messages[1]["role"] == "user"
    assert "近 7 天" in messages[1]["content"]
    assert '"total_questions": 1' in messages[1]["content"]


def test_rule_based_analysis_empty_data_and_risk_priority():
    now = datetime(2026, 10, 25, 10, 0, 0)
    empty = build_rule_based_dashboard_analysis(
        {"overview": {"total_questions": 0}},
        7,
        now=now,
        serialize_now=lambda value: value.isoformat(),
    )
    assert empty["generated"] is False
    assert empty["model"] == "rule-based"
    assert empty["actions"][0]["type"] == "practice"

    payload = {
        "overview": {
            "today_questions": 2,
            "due_review_count": 3,
            "consecutive_days": 4,
            "total_questions": 10,
            "total_accuracy": 0.6,
        },
        "trends": {"total_questions": 3, "active_days": 2, "avg_accuracy": 0.5},
        "subjects": {
            "items": [
                {"label": "A", "accuracy": 0.8},
                {"label": "B", "accuracy": 0.6},
            ]
        },
        "review_risk": {
            "high_forget_count": 2,
            "stuck_questions": 1,
            "top_topics": [{"topic": "topic"}],
        },
    }
    analysis = build_rule_based_dashboard_analysis(
        payload,
        7,
        now=now,
        serialize_now=lambda value: value.isoformat(),
    )

    assert analysis["generated"] is False
    assert analysis["summary"] == "学习数据良好，但到期复习3道需尽快处理。"
    assert analysis["actions"][0]["type"] == "review"
    assert analysis["actions"][1]["type"] == "wrong"
    assert analysis["actions"][2]["type"] == "subject"
    assert any("topic" in risk for risk in analysis["risks"])


def test_knowledge_point_stats_project_subject_rows():
    stats = build_knowledge_point_stats(
        [
            ("data_structure", 4, 1),
            ("network", None, None),
        ]
    )

    assert stats == [
        {
            "knowledge_point": "data_structure",
            "mastery_rate": 0.25,
            "mastered": 1,
            "total_wrong": 4,
        },
        {
            "knowledge_point": "network",
            "mastery_rate": 0.0,
            "mastered": 0,
            "total_wrong": 0,
        },
    ]


def test_local_ai_diagnosis_sorts_weak_and_strong_points():
    diagnosis = build_local_ai_diagnosis(
        knowledge_point_stats=[
            {"knowledge_point": "a", "mastery_rate": 0.4, "total_wrong": 2},
            {"knowledge_point": "b", "mastery_rate": 0.2, "total_wrong": 5},
            {"knowledge_point": "c", "mastery_rate": 0.6, "total_wrong": 1},
            {"knowledge_point": "d", "mastery_rate": 0.8, "total_wrong": 2},
            {"knowledge_point": "e", "mastery_rate": 0.9, "total_wrong": 1},
        ],
        subject_count=5,
        total_questions=30,
    )

    assert [item["knowledge_point"] for item in diagnosis["weak_points"]] == ["b", "a"]
    assert [item["knowledge_point"] for item in diagnosis["strong_points"]] == ["e", "d"]
    assert diagnosis["learning_suggestions"][0].startswith("优先复盘b错题")
    assert diagnosis["learning_suggestions"][1].startswith("其次巩固a")
    assert "累计到 50 题以上" in diagnosis["learning_suggestions"][2]
    assert diagnosis["summary"] == "基于最近60天5个科目的错题数据生成诊断。"
    assert diagnosis["generated"] is False


def test_local_ai_diagnosis_provider_failure_summary_and_caps():
    diagnosis = build_local_ai_diagnosis(
        knowledge_point_stats=[
            {"knowledge_point": f"w{i}", "mastery_rate": 0.1, "total_wrong": i}
            for i in range(5)
        ],
        subject_count=5,
        total_questions=100,
        provider_failed=True,
    )

    assert len(diagnosis["weak_points"]) == 3
    assert diagnosis["learning_suggestions"][-1] == "优先处理重复出错且尚未掌握的题目，并按复习计划回看"
    assert diagnosis["summary"].startswith("AI 模型响应较慢")
