"""Compatibility baseline for study-report pure projections."""

from __future__ import annotations

from app.services.study_report_projection import (
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
