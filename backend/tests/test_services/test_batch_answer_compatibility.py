"""Real compatibility baseline for batch answer parsing and normalization."""

from __future__ import annotations

import pytest

from app.services.batch_answer_service import (
    normalize_single_answer,
    parse_answer_string,
)


class TestParseAnswerString:
    def test_empty_returns_empty(self):
        assert parse_answer_string("") == []
        assert parse_answer_string("   ") == []

    def test_compact_single_choice_string(self):
        assert parse_answer_string("ABCD") == ["A", "B", "C", "D"]

    def test_comma_separated(self):
        assert parse_answer_string("A,B,C,D") == ["A", "B", "C", "D"]

    def test_chinese_comma_separated(self):
        assert parse_answer_string("A，B，C") == ["A", "B", "C"]

    def test_pipe_separated(self):
        assert parse_answer_string("A|B|C") == ["A", "B", "C"]

    def test_space_separated(self):
        assert parse_answer_string("A B C") == ["A", "B", "C"]

    def test_multi_choice_with_separator(self):
        result = parse_answer_string("A,AC,B,BCD,D")
        assert result == ["A", "AC", "B", "BCD", "D"]

    def test_lowercase_uppercased(self):
        assert parse_answer_string("abcd") == ["A", "B", "C", "D"]

    def test_newline_separated(self):
        result = parse_answer_string("A\nB\nC")
        assert result == ["A", "B", "C"]


class TestNormalizeSingleAnswer:
    def test_empty_returns_error(self):
        result, errors = normalize_single_answer("", "single_choice")
        assert result is None
        assert len(errors) > 0

    def test_single_choice_valid(self):
        result, errors = normalize_single_answer("B", "single_choice", {"A": {}, "B": {}, "C": {}})
        assert result == "B"
        assert errors == []

    def test_single_choice_lowercase(self):
        result, errors = normalize_single_answer("b", "single_choice", {"A": {}, "B": {}})
        assert result == "B"
        assert errors == []

    def test_single_choice_invalid_length(self):
        result, errors = normalize_single_answer("AB", "single_choice", {"A": {}, "B": {}})
        assert result is None
        assert len(errors) > 0

    def test_single_choice_out_of_range(self):
        result, errors = normalize_single_answer("Z", "single_choice", {"A": {}, "B": {}})
        assert result is None
        assert len(errors) > 0

    def test_multi_choice_dedup_sorted(self):
        result, errors = normalize_single_answer("CAAC", "multiple_choice")
        assert result == "AC"
        assert errors == []

    def test_true_false_true(self):
        for val in ["T", "true", "对", "正确", "√", "1"]:
            result, errors = normalize_single_answer(val, "true_false")
            assert result == "T", f"Failed for {val}"

    def test_true_false_false(self):
        for val in ["F", "false", "错", "错误", "×", "0"]:
            result, errors = normalize_single_answer(val, "true_false")
            assert result == "F", f"Failed for {val}"

    def test_unsupported_type_returns_error(self):
        result, errors = normalize_single_answer("A", "nonexistent_type")
        assert result is None
        assert len(errors) > 0
