"""Compatibility baseline for learning-AI provider payload normalization."""

from __future__ import annotations

from app.services.stats_ai_projection import normalize_knowledge_points


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
