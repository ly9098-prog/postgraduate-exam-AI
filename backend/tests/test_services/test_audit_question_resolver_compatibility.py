"""Real compatibility baseline for audit question content text extraction."""

from __future__ import annotations

import pytest

from app.services.audit_question_resolver import extract_question_content_text


class TestExtractQuestionContentText:
    def test_none_returns_none(self):
        assert extract_question_content_text(None) is None

    def test_string_returns_self(self):
        assert extract_question_content_text("hello") == "hello"

    def test_dict_with_text_key(self):
        assert extract_question_content_text({"text": "question text"}) == "question text"

    def test_dict_with_stem_key(self):
        assert extract_question_content_text({"stem": "question stem"}) == "question stem"

    def test_dict_falls_to_json(self):
        result = extract_question_content_text({"unknown_key": "value"})
        assert result is not None
        assert "unknown_key" in result

    def test_dict_empty_string_values_skipped(self):
        result = extract_question_content_text({"text": "", "stem": "real"})
        assert result == "real"

    def test_list_of_dicts(self):
        result = extract_question_content_text([{"value": "a"}, {"text": "b"}])
        assert "a" in result
        assert "b" in result

    def test_list_of_strings(self):
        result = extract_question_content_text(["hello", "world"])
        assert "hello" in result
        assert "world" in result

    def test_empty_list_returns_none(self):
        assert extract_question_content_text([]) is None

    def test_non_string_non_dict_non_list(self):
        result = extract_question_content_text(123)
        assert result == "123"

    def test_dict_key_priority(self):
        """text takes priority over stem."""
        result = extract_question_content_text({"text": "from_text", "stem": "from_stem"})
        assert result == "from_text"
