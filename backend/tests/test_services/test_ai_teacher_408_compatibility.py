"""Real compatibility baseline for AI teacher 408 pure helper functions."""

from __future__ import annotations

import pytest

from app.services.ai_teacher_408_service import (
    _bounded,
    _clean_points,
    _clean_str,
    _parse_json_object,
    _stem_text,
)


class TestStemText:
    def test_dict_with_text_key(self):
        assert _stem_text({"text": "hello"}) == "hello"

    def test_dict_with_stem_key(self):
        assert _stem_text({"stem": "question"}) == "question"

    def test_dict_with_segments(self):
        result = _stem_text({"segments": [{"text": "a"}, {"text": "b"}]})
        assert "a" in result and "b" in result

    def test_string_content(self):
        assert _stem_text("plain raw") == "plain raw"

    def test_none_content(self):
        assert _stem_text(None) == ""


class TestBounded:
    def test_short_string_unchanged(self):
        assert _bounded("hello", 100) == "hello"

    def test_long_string_truncated(self):
        assert _bounded("x" * 200, 100) == "x" * 100

    def test_dict_within_limit_unchanged(self):
        result = _bounded({"a": 1}, 100)
        assert result == {"a": 1}

    def test_dict_over_limit_truncated(self):
        result = _bounded({"a": "x" * 200}, 50)
        assert isinstance(result, str)
        assert len(result) <= 50


class TestCleanStr:
    def test_strips_whitespace(self):
        assert _clean_str("  hello  ") == "hello"

    def test_truncates_to_limit(self):
        assert _clean_str("x" * 2000, limit=100) == "x" * 100

    def test_none_returns_empty(self):
        assert _clean_str(None) == ""


class TestCleanPoints:
    def test_non_list_returns_empty(self):
        assert _clean_points("string") == []
        assert _clean_points(None) == []

    def test_filters_empty_strings(self):
        assert _clean_points(["a", "", "  ", "b"]) == ["a", "b"]

    def test_limits_items(self):
        result = _clean_points(["a", "b", "c", "d", "e", "f"], max_items=3)
        assert len(result) == 3

    def test_truncates_each_item(self):
        result = _clean_points(["x" * 1000], item_limit=50)
        assert len(result[0]) <= 50


class TestParseJsonObject:
    def test_empty_returns_none(self):
        assert _parse_json_object("") is None
        assert _parse_json_object(None) is None

    def test_plain_json(self):
        assert _parse_json_object('{"key": "value"}') == {"key": "value"}

    def test_markdown_fenced(self):
        assert _parse_json_object('```json\n{"k": 1}\n```') == {"k": 1}

    def test_text_around_json(self):
        assert _parse_json_object('result: {"a": 1} end') == {"a": 1}

    def test_invalid_returns_none(self):
        assert _parse_json_object("not json") is None

    def test_array_returns_none(self):
        assert _parse_json_object("[1, 2, 3]") is None
