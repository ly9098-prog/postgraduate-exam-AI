"""Compatibility baseline for AI analysis content and answer-check parsing.

These tests do not call an external model.  They pin the robust parser and
machine-verifiable answer-check contract used before AI responses are cached
or exposed to clients.
"""

from __future__ import annotations

import pytest

from app.services.ai_service import (
    _canonical_answer_check_list,
    _canonical_answer_echo,
    _decode_structured_content,
    _extract_answer_check,
    _looks_like_structured_analysis_text,
    _normalize_ai_analysis,
    _strip_code_fence,
    _validate_answer_check,
    is_valid_ai_analysis,
    parse_error_analysis_content,
)


class TestStripCodeFence:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ('```json\n{"a":1}\n```', '{"a":1}'),
            ("```\nplain\n```", "plain"),
            ('```json\n{"a":1}', '{"a":1}'),
            ('{"a":1}\n```', '{"a":1}'),
            ("  plain  ", "plain"),
            ("", ""),
        ],
    )
    def test_fence_shapes(self, raw, expected):
        assert _strip_code_fence(raw) == expected


class TestStructuredContentDetection:
    def test_json_and_array_prefixes_are_structured(self):
        assert _looks_like_structured_analysis_text('{"a":1}') is True
        assert _looks_like_structured_analysis_text("[1,2]") is True

    def test_quoted_known_key_is_structured(self):
        assert (
            _looks_like_structured_analysis_text('text "mistake_diagnosis": "x"')
            is True
        )

    def test_prose_words_are_not_structured(self):
        assert (
            _looks_like_structured_analysis_text("task and knowledge are prose")
            is False
        )

    def test_empty_is_not_structured(self):
        assert _looks_like_structured_analysis_text("") is False


class TestDecodeStructuredContent:
    def test_json_with_surrounding_text(self):
        assert _decode_structured_content('before {"a": 1} after') == {"a": 1}

    def test_python_literal_is_supported(self):
        assert _decode_structured_content("{'a': 1}") == {"a": 1}

    def test_code_fence_is_removed(self):
        assert _decode_structured_content('```json\n{"a":1}\n```') == {"a": 1}

    def test_invalid_content_returns_none(self):
        assert _decode_structured_content("not structured") is None
        assert _decode_structured_content("") is None


class TestParseErrorAnalysisContent:
    def test_empty_returns_empty_canonical_fields(self):
        assert parse_error_analysis_content("") == {
            "mistake_diagnosis": "",
            "knowledge_patch": "",
            "review_task": "",
        }

    def test_canonical_json(self):
        raw = (
            '{"mistake_diagnosis":"诊断","knowledge_patch":"补漏","review_task":"任务"}'
        )

        assert parse_error_analysis_content(raw) == {
            "mistake_diagnosis": "诊断",
            "knowledge_patch": "补漏",
            "review_task": "任务",
        }

    def test_fenced_json_with_surrounding_text(self):
        raw = '模型返回：```json\n{"错因诊断":"诊断","补漏重点":"补漏","复练任务":"任务"}\n```'

        assert parse_error_analysis_content(raw) == {
            "mistake_diagnosis": "诊断",
            "knowledge_patch": "补漏",
            "review_task": "任务",
        }

    def test_camel_case_and_wrapper_fields(self):
        raw = '{"data":{"mistakeDiagnosis":"诊断","knowledgePatch":"补漏","reviewTask":"任务"}}'

        assert parse_error_analysis_content(raw) == {
            "mistake_diagnosis": "诊断",
            "knowledge_patch": "补漏",
            "review_task": "任务",
        }

    def test_titled_plain_text(self):
        raw = "错因诊断：诊断\n补漏重点：补漏\n复练任务：任务"

        assert parse_error_analysis_content(raw) == {
            "mistake_diagnosis": "诊断",
            "knowledge_patch": "补漏",
            "review_task": "任务",
        }

    def test_malformed_structured_text_is_not_downgraded_to_prose(self):
        raw = '```json\n{"mistake_diagnosis":'

        assert parse_error_analysis_content(raw) == {
            "mistake_diagnosis": "",
            "knowledge_patch": "",
            "review_task": "",
        }

    def test_embedded_json_in_canonical_field_is_unwrapped(self):
        raw = (
            '{"mistake_diagnosis":"```json\\n'
            '{\\"knowledge_patch\\":\\"补漏\\",'
            '\\"review_task\\":\\"任务\\"}\\n```"}'
        )

        assert parse_error_analysis_content(raw) == {
            "mistake_diagnosis": "",
            "knowledge_patch": "补漏",
            "review_task": "任务",
        }


class TestAnalysisValidity:
    @pytest.mark.parametrize(
        "content",
        [
            {"mistake_diagnosis": "x"},
            {"knowledge_patch": "x"},
            {"review_task": "x"},
        ],
    )
    def test_any_non_empty_field_is_valid(self, content):
        assert is_valid_ai_analysis(content) is True

    def test_empty_or_whitespace_fields_are_invalid(self):
        assert is_valid_ai_analysis({}) is False
        assert is_valid_ai_analysis({"mistake_diagnosis": " "}) is False

    def test_normalize_empty_returns_empty_contract(self):
        assert _normalize_ai_analysis(None) == {
            "mistake_diagnosis": "",
            "knowledge_patch": "",
            "review_task": "",
        }

    def test_normalize_cached_alias_fields(self):
        assert _normalize_ai_analysis({"diagnosis": "诊断", "task": "任务"}) == {
            "mistake_diagnosis": "诊断",
            "knowledge_patch": "",
            "review_task": "任务",
        }


class TestAnswerCheckParsing:
    def test_direct_and_nested_answer_check(self):
        direct = {"answer_check": {"correct_answer": "A"}}
        wrapped = {"data": {"answerCheck": {"correct_answer": "A"}}}
        encoded = '{"作答核对":{"correct_answer":"A"}}'

        assert _extract_answer_check(direct) == {"correct_answer": "A"}
        assert _extract_answer_check(wrapped) == {"correct_answer": "A"}
        assert _extract_answer_check(encoded) == {"correct_answer": "A"}

    def test_missing_answer_check_returns_none(self):
        assert _extract_answer_check({"diagnosis": "x"}) is None

    @pytest.mark.parametrize(
        ("raw", "expected", "canonical"),
        [
            ("b", "B", "B"),
            ("A,C", "C,A", "A,C"),
            ("A，C", "A,C", "A,C"),
            ("答案一", "答案一", "答案一"),
        ],
    )
    def test_choice_echo_is_order_and_delimiter_insensitive(
        self, raw, expected, canonical
    ):
        assert _canonical_answer_echo(raw, expected) == canonical

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (None, []),
            ("A,C Ⅰ", ["A", "C", "I"]),
            (["A", {"label": "C"}, "A"], ["A", "C"]),
            ({"key": "B"}, ["B"]),
            (42, ["42"]),
        ],
    )
    def test_answer_check_list_normalization(self, value, expected):
        assert _canonical_answer_check_list(value) == expected


class TestValidateAnswerCheck:
    def test_matching_check_passes(self):
        raw = '{"answer_check":{"correct_answer":"B","user_answer":"A,C","missing":["A"],"extra":["D"]}}'
        expected = {
            "correct_answer": "B",
            "user_answer": "C,A",
            "missing": ["A"],
            "extra": ["D"],
        }

        valid, reason, actual = _validate_answer_check(raw, expected)

        assert valid is True
        assert reason == ""
        assert actual == {
            "correct_answer": "B",
            "user_answer": "A,C",
            "missing": ["A"],
            "extra": ["D"],
        }

    def test_missing_check_is_rejected(self):
        valid, reason, actual = _validate_answer_check("{}", {})

        assert valid is False
        assert reason == "answer_check_missing"
        assert actual is None

    @pytest.mark.parametrize(
        ("actual_value", "expected_value", "reason"),
        [
            ("A", "B", "answer_check_correct_mismatch"),
            ("A", "C", "answer_check_user_mismatch"),
        ],
    )
    def test_answer_mismatch_reasons(self, actual_value, expected_value, reason):
        raw = '{"answer_check":{"correct_answer":"A","user_answer":"A"}}'
        expected = {
            "correct_answer": "B" if reason.endswith("correct_mismatch") else "A",
            "user_answer": "C" if reason.endswith("user_mismatch") else "A",
        }

        valid, parsed_reason, _ = _validate_answer_check(raw, expected)

        assert valid is False
        assert parsed_reason == reason

    def test_missing_and_extra_mismatch_reasons(self):
        raw = '{"answer_check":{"correct_answer":"A","user_answer":"A","missing":["B"],"extra":["C"]}}'
        expected = {
            "correct_answer": "A",
            "user_answer": "A",
            "missing": ["A"],
            "extra": ["C"],
        }

        valid, reason, _ = _validate_answer_check(raw, expected)

        assert valid is False
        assert reason == "answer_check_missing_mismatch"
