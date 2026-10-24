"""Tests for the extracted review text sanitization helpers."""

from __future__ import annotations

from app.services.review_text_utils import (
    contains_code,
    fix_code_operator_splits,
    sanitize_review_content,
    sanitize_review_option_value,
    sanitize_review_options,
    sanitize_review_text,
)


class TestContainsCode:
    def test_empty_returns_false(self):
        assert contains_code("") is False
        assert contains_code(None) is False

    def test_plain_text_returns_false(self):
        assert contains_code("这是一段普通的文字") is False

    def test_code_signals_detected(self):
        text = "int main() { return 0; }"
        assert contains_code(text) is True

    def test_ds_keywords_detected(self):
        text = "LNode *p = (LNode *)malloc(sizeof(LNode));"
        assert contains_code(text) is True


class TestFixCodeOperatorSplits:
    def test_no_newline_unchanged(self):
        assert fix_code_operator_splits("hello") == "hello"

    def test_merges_operator_split_lines(self):
        text = "a +\nb"
        result = fix_code_operator_splits(text)
        assert result == "a +b"

    def test_preserves_non_split_lines(self):
        text = "line1\nline2"
        assert fix_code_operator_splits(text) == "line1\nline2"


class TestSanitizeReviewText:
    def test_none_returns_none(self):
        assert sanitize_review_text(None) is None

    def test_non_string_passes_through(self):
        assert sanitize_review_text(123) == 123

    def test_carriage_returns_normalized(self):
        result = sanitize_review_text("line1\r\nline2\rline3")
        assert "\r" not in result

    def test_code_text_uses_code_path(self):
        text = "int x = 1;\nreturn x +\n2;"
        result = sanitize_review_text(text)
        assert isinstance(result, str)


class TestSanitizeReviewContent:
    def test_none_returns_empty_dict(self):
        result = sanitize_review_content(None)
        assert result == {}

    def test_string_wrapped_as_text(self):
        result = sanitize_review_content("hello")
        assert "text" in result

    def test_dict_preserved(self):
        result = sanitize_review_content({"text": "hello", "extra": "field"})
        assert result.get("extra") == "field"

    def test_stem_copied_to_text(self):
        result = sanitize_review_content({"stem": "world"})
        assert result.get("text") == "world"

    def test_visual_region_fields_stripped(self):
        result = sanitize_review_content(
            {
                "text": "hello",
                "visual_regions": ["region1"],
                "visual_region_ids": [1],
            }
        )
        assert "visual_regions" not in result
        assert "visual_region_ids" not in result


class TestSanitizeReviewOptions:
    def test_non_dict_returns_empty(self):
        assert sanitize_review_options(None) == {}
        assert sanitize_review_options("not a dict") == {}

    def test_string_option_flattened(self):
        result = sanitize_review_options({"A": "line1\nline2"})
        assert "\n" not in result["A"]

    def test_dict_option_text_normalized(self):
        result = sanitize_review_options({"A": {"text": "line1\r\nline2"}})
        assert "\r" not in result["A"]["text"]

    def test_dict_option_falls_back_to_value(self):
        result = sanitize_review_options({"A": {"value": "test"}})
        assert "text" in result["A"]


class TestSanitizeReviewOptionValue:
    def test_string_normalizes_newlines(self):
        result = sanitize_review_option_value("line1\r\nline2")
        assert "\r" not in result
        assert "\n" not in result

    def test_non_string_non_dict_passes_through(self):
        assert sanitize_review_option_value(42) == 42
        assert sanitize_review_option_value(None) is None
