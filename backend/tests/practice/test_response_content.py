"""Regression checks for the student-facing content projection boundary."""

from copy import deepcopy

import pytest

from app.services.practice.response_content import (
    ensure_true_false_options,
    sanitize_question_content,
    sanitize_question_options,
    sanitize_text_field,
)


@pytest.mark.parametrize("value", [None, "", [], 0])
def test_non_mapping_content_and_options_are_preserved(value):
    assert sanitize_question_content(value) is value
    assert sanitize_question_options(value) is value


def test_student_projection_does_not_mutate_revision():
    source = {
        "text": "current stem",
        "source_snapshot_url": "/private/source.png",
        "source_snapshot_full_page": True,
        "visual_regions": [{"id": 1}],
        "visual_region_ids": [1],
        "analysis": "retained",
    }
    original = deepcopy(source)
    projected = sanitize_question_content(source)
    assert source == original
    assert projected is not source
    assert projected["text"] == "current stem"
    assert projected["analysis"] == "retained"
    assert not any(key in projected for key in (
        "source_snapshot_url", "source_snapshot_full_page", "visual_regions", "visual_region_ids",
    ))


def test_rich_options_keep_metadata_without_mutation():
    source = {
        "A": {"text": "I、II\r\nIII", "segments": [{"type": "image", "url": "/a.png"}]},
        "B": {"value": "x +=\r\n 2", "tag": "legacy"},
        "C": None,
        "D": 7,
    }
    original = deepcopy(source)
    result = sanitize_question_options(source)
    assert source == original
    assert result["A"] == {**source["A"], "text": "I、II III"}
    assert result["B"] == {**source["B"], "text": "x +=2"}
    assert result["C"] is None
    assert result["D"] == 7
    assert result["A"] is not source["A"]


def test_code_preserves_indentation_and_repeated_statements():
    source = "while (x > 0) {\r\n    x--;\r\n    x--;\r\n    x +=\r\n      2;\r\n}"
    expected = "while (x > 0) {\n    x--;\n    x--;\n    x +=2;\n}"
    assert sanitize_text_field(source) == expected
    assert sanitize_text_field(expected) == expected


def test_fallback_applies_only_to_empty_true_false_options():
    supplied = {"A": "custom"}
    assert ensure_true_false_options("true_false", supplied) is supplied
    assert ensure_true_false_options("single_choice", None) is None
    assert ensure_true_false_options("true_false", {}) == {"A": "正确", "B": "错误"}
