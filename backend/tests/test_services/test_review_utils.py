"""Tests for the extracted review mastery and error classification helpers."""

from __future__ import annotations

import pytest

from app.services.review_utils import (
    _REVIEW_AUTO_MASTER_REPETITIONS,
    _REVIEW_MASTERY_BY_REPETITIONS,
    review_auto_mastered,
    review_item_error_meta,
    review_mastery_percent,
)


class TestReviewMasteryPercent:
    @pytest.mark.parametrize(
        "reps,expected",
        [
            (0, 20),
            (1, 45),
            (2, 65),
            (3, 80),
            (4, 90),
        ],
    )
    def test_known_repetitions(self, reps, expected):
        assert review_mastery_percent(reps) == expected

    def test_five_or_more_is_100(self):
        assert review_mastery_percent(5) == 100
        assert review_mastery_percent(100) == 100

    def test_none_defaults_to_20(self):
        assert review_mastery_percent(None) == 20

    def test_negative_defaults_to_20(self):
        assert review_mastery_percent(-5) == 20

    def test_zero_is_20(self):
        assert review_mastery_percent(0) == 20


class TestReviewAutoMastered:
    @pytest.mark.parametrize(
        "reps,expected",
        [
            (0, False),
            (1, False),
            (2, False),
            (3, True),
            (4, True),
            (5, True),
        ],
    )
    def test_mastery_threshold(self, reps, expected):
        assert review_auto_mastered(reps) is expected

    def test_none_is_false(self):
        assert review_auto_mastered(None) is False

    def test_negative_is_false(self):
        assert review_auto_mastered(-10) is False


class TestReviewItemErrorMeta:
    def test_request_conflict(self):
        code, retry, fetch = review_item_error_meta("request_id 已用于不同提交")
        assert code == "REVIEW_REQUEST_CONFLICT"
        assert retry is False
        assert fetch is True

    def test_schedule_missing(self):
        code, _, _ = review_item_error_meta("复习记录不存在")
        assert code == "REVIEW_SCHEDULE_MISSING"

    def test_task_mismatch(self):
        code, _, _ = review_item_error_meta("题目与复习记录不匹配")
        assert code == "REVIEW_TASK_MISMATCH"

    def test_version_stale(self):
        code, _, _ = review_item_error_meta("版本已更新")
        assert code == "REVIEW_VERSION_STALE"

    def test_version_not_found(self):
        code, _, _ = review_item_error_meta("版本不存在")
        assert code == "REVIEW_VERSION_STALE"

    def test_task_removed(self):
        code, _, _ = review_item_error_meta("已从复习队列移除")
        assert code == "REVIEW_TASK_STALE"

    def test_task_mastered(self):
        code, _, _ = review_item_error_meta("已标记掌握")
        assert code == "REVIEW_TASK_STALE"

    def test_task_already_submitted(self):
        code, _, _ = review_item_error_meta("已经提交")
        assert code == "REVIEW_TASK_STALE"

    def test_task_expired(self):
        code, _, _ = review_item_error_meta("已失效")
        assert code == "REVIEW_TASK_STALE"

    def test_unknown_error(self):
        code, retry, fetch = review_item_error_meta("some unknown error")
        assert code == "REVIEW_ITEM_REJECTED"
        assert retry is False
        assert fetch is True

    def test_empty_message(self):
        code, _, _ = review_item_error_meta("")
        assert code == "REVIEW_ITEM_REJECTED"

    def test_none_message(self):
        code, _, _ = review_item_error_meta(None)
        assert code == "REVIEW_ITEM_REJECTED"
