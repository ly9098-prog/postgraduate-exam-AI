"""Tests for the extracted practice normalization helpers."""

from datetime import datetime, timezone

import pytest

from app.services.practice.normalization import (
    PRACTICE_ALLOWED_MODES,
    PRACTICE_ANSWER_MAX_USED_TIME_SEC,
    PRACTICE_SESSION_MAX_DURATION_SEC,
    canonical_408_subject,
    detect_408_subject_mismatch,
    normalize_answer_used_time,
    normalize_practice_request_id,
    normalize_practice_session,
    normalize_true_false_answer,
    parse_session_datetime,
    question_stem_for_subject_guard,
)


class TestNormalizeAnswerUsedTime:
    def test_none_returns_none(self):
        assert normalize_answer_used_time(None) is None

    def test_valid_int(self):
        assert normalize_answer_used_time(30) == 30

    def test_valid_string(self):
        assert normalize_answer_used_time("30") == 30

    def test_non_int_raises(self):
        with pytest.raises(ValueError, match="必须为整数"):
            normalize_answer_used_time("abc")

    def test_negative_raises(self):
        with pytest.raises(ValueError, match="必须在"):
            normalize_answer_used_time(-1)

    def test_over_limit_raises(self):
        with pytest.raises(ValueError, match="必须在"):
            normalize_answer_used_time(PRACTICE_ANSWER_MAX_USED_TIME_SEC + 1)


class TestParseSessionDatetime:
    def test_none_returns_none(self):
        assert parse_session_datetime(None) is None

    def test_empty_string_returns_none(self):
        assert parse_session_datetime("") is None
        assert parse_session_datetime("  ") is None

    def test_iso_with_z(self):
        result = parse_session_datetime("2025-08-08T10:00:00Z")
        assert result is not None
        assert isinstance(result, datetime)

    def test_iso_with_offset(self):
        result = parse_session_datetime("2025-08-08T10:00:00+08:00")
        assert result is not None

    def test_invalid_string_returns_none(self):
        assert parse_session_datetime("not-a-date") is None

    def test_datetime_object(self):
        dt = datetime(2025, 8, 8, 10, 0, 0, tzinfo=timezone.utc)
        result = parse_session_datetime(dt)
        assert result is not None


class TestNormalizePracticeRequestId:
    def test_empty_returns_none(self):
        assert normalize_practice_request_id("") is None
        assert normalize_practice_request_id(None) is None

    def test_valid_id(self):
        assert normalize_practice_request_id("abc-123") == "abc-123"

    def test_strips_whitespace(self):
        assert normalize_practice_request_id("  abc  ") == "abc"

    def test_too_long_raises(self):
        with pytest.raises(ValueError, match="request_id"):
            normalize_practice_request_id("x" * 129)


class TestNormalizePracticeSession:
    def _meta(self, **overrides):
        base = {
            "started_at": "2025-08-08T10:00:00Z",
            "finished_at": "2025-08-08T10:10:00Z",
            "duration_sec": 600,
            "request_id": "test-req",
            "subject_id": 1,
            "mode": "random",
            "answered_count": 5,
            "question_count": 5,
        }
        base.update(overrides)
        return base

    def test_valid_session(self):
        out = normalize_practice_session(
            self._meta(), user_id=1, answered_count=5, total_correct=3, total_wrong=2
        )
        assert out["user_id"] == 1
        assert out["status"] == "completed"
        assert out["answered_count"] == 5
        assert out["correct_count"] == 3
        assert out["wrong_count"] == 2

    def test_empty_session_raises(self):
        with pytest.raises(ValueError, match="session 不能为空"):
            normalize_practice_session(
                {}, user_id=1, answered_count=0, total_correct=0, total_wrong=0
            )

    def test_finished_before_started_raises(self):
        meta = self._meta(
            started_at="2025-08-08T10:10:00Z", finished_at="2025-08-08T10:00:00Z"
        )
        with pytest.raises(ValueError, match="不得早于"):
            normalize_practice_session(
                meta, user_id=1, answered_count=5, total_correct=0, total_wrong=5
            )

    def test_invalid_mode_raises(self):
        meta = self._meta(mode="invalid_mode")
        with pytest.raises(ValueError, match="mode 无效"):
            normalize_practice_session(
                meta, user_id=1, answered_count=5, total_correct=0, total_wrong=5
            )

    def test_answered_count_mismatch_raises(self):
        meta = self._meta(answered_count=10)
        with pytest.raises(ValueError, match="answered_count"):
            normalize_practice_session(
                meta, user_id=1, answered_count=5, total_correct=0, total_wrong=5
            )

    def test_duration_exceeding_wall_raises(self):
        meta = self._meta(duration_sec=999999999)
        with pytest.raises(ValueError, match="墙钟"):
            normalize_practice_session(
                meta, user_id=1, answered_count=5, total_correct=0, total_wrong=5
            )

    def test_duration_over_session_limit_raises(self):
        meta = self._meta(
            duration_sec=PRACTICE_SESSION_MAX_DURATION_SEC + 1,
            started_at="2025-08-08T00:00:00Z",
            finished_at="2025-08-09T02:00:00Z",
        )
        with pytest.raises(ValueError, match="允许上限"):
            normalize_practice_session(
                meta, user_id=1, answered_count=5, total_correct=0, total_wrong=5
            )


class TestNormalizeTrueFalseAnswer:
    @pytest.mark.parametrize(
        "value", ["A", "a", "true", "对", "是", "正确", "t", "yes", "1"]
    )
    def test_true_values_return_a(self, value):
        assert normalize_true_false_answer(value) == "A"

    @pytest.mark.parametrize(
        "value", ["B", "b", "false", "错", "否", "错误", "f", "no", "0"]
    )
    def test_false_values_return_b(self, value):
        assert normalize_true_false_answer(value) == "B"

    def test_unknown_value_uppercased(self):
        assert normalize_true_false_answer("xyz") == "XYZ"

    def test_empty_returns_empty(self):
        assert normalize_true_false_answer("") == ""


class TestCanonical408Subject:
    def test_valid_code(self):
        assert canonical_408_subject("data_structure") == "data_structure"

    def test_case_insensitive(self):
        assert canonical_408_subject("DATA_STRUCTURE") == "data_structure"

    def test_invalid_code_returns_none(self):
        assert canonical_408_subject("not_real") is None

    def test_none_returns_none(self):
        assert canonical_408_subject(None) is None

    def test_empty_returns_none(self):
        assert canonical_408_subject("") is None

    def test_name_is_ignored(self):
        # name should not mask a bad code
        assert canonical_408_subject("bad_code", name="data_structure") is None


class TestQuestionStemForSubjectGuard:
    def test_none_returns_empty(self):
        assert question_stem_for_subject_guard(None) == ""

    def test_not_dict_returns_empty(self):
        assert question_stem_for_subject_guard("not a dict") == ""

    def test_text_field(self):
        assert question_stem_for_subject_guard({"text": "Hello"}) == "hello"

    def test_stem_field(self):
        assert question_stem_for_subject_guard({"stem": "World"}) == "world"

    def test_text_takes_precedence(self):
        assert (
            question_stem_for_subject_guard({"text": "first", "stem": "second"})
            == "first"
        )


class TestDetect408SubjectMismatch:
    def test_no_stem_returns_none(self):
        result, scores = detect_408_subject_mismatch(
            subject_code="data_structure", subject_name=None, stem=""
        )
        assert result is None
        assert scores == {}

    def test_unknown_subject_returns_none(self):
        result, scores = detect_408_subject_mismatch(
            subject_code="not_408", subject_name=None, stem="进程 段表"
        )
        assert result is None
        assert scores == {}

    def test_os_anchors_in_ds_subject_detected(self):
        result, scores = detect_408_subject_mismatch(
            subject_code="data_structure",
            subject_name="数据结构",
            stem="进程 段表 段号 段内地址 死锁",
        )
        # OS anchors should win by >= 2 over the expected data_structure score
        assert result == "operating_system"
        assert scores.get("operating_system", 0) >= 2

    def test_matching_subject_returns_none(self):
        result, scores = detect_408_subject_mismatch(
            subject_code="data_structure",
            subject_name="数据结构",
            stem="二叉树 链表 散列表",
        )
        # The stem matches data_structure, so no mismatch
        assert result is None

    def test_low_confidence_returns_none(self):
        result, scores = detect_408_subject_mismatch(
            subject_code="data_structure",
            subject_name="数据结构",
            stem="进程",
        )
        # Only one OS anchor, below the threshold
        assert result is None
