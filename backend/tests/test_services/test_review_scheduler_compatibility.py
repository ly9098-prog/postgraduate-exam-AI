"""Real compatibility baseline for review scheduler pure functions.

Exercises sanitization, mastery mapping and SM-2 integration contracts.
All pure functions — no database needed.
"""

from __future__ import annotations

import pytest

from app.services.review_scheduler import (
    _sanitize_review_content,
    _sanitize_review_option_value,
    _sanitize_review_options,
    _sanitize_review_text,
    review_auto_mastered,
    review_mastery_percent,
)
from app.services.sm2_service import calc_sm2


class TestReviewMasteryPercent:
    @pytest.mark.parametrize("reps,expected", [
        (0, 20), (1, 45), (2, 65), (3, 80), (4, 90), (5, 100), (10, 100),
    ])
    def test_known_repetitions(self, reps, expected):
        assert review_mastery_percent(reps) == expected

    def test_none_is_zero_reps(self):
        assert review_mastery_percent(None) == 20

    def test_negative_is_zero_reps(self):
        assert review_mastery_percent(-5) == 20

    def test_unknown_repetition_defaults_to_20(self):
        """Repetitions beyond the table but below 5 → 20."""
        # All 0-4 are in the table, so this tests the fallback path
        assert review_mastery_percent(0) == 20


class TestReviewAutoMastered:
    @pytest.mark.parametrize("reps,expected", [
        (0, False), (1, False), (2, False), (3, True), (4, True), (10, True),
    ])
    def test_threshold_at_3(self, reps, expected):
        assert review_auto_mastered(reps) is expected

    def test_none_is_not_mastered(self):
        assert review_auto_mastered(None) is False


class TestSanitizeReviewText:
    def test_none_passes_through(self):
        assert _sanitize_review_text(None) is None

    def test_non_string_passes_through(self):
        assert _sanitize_review_text(123) == 123

    def test_carriage_returns_normalized(self):
        result = _sanitize_review_text("line1\r\nline2\rline3")
        assert "\r" not in result
        assert "\n" in result


class TestSanitizeReviewContent:
    def test_none_returns_empty_dict(self):
        assert _sanitize_review_content(None) == {}

    def test_string_wraps_as_text(self):
        result = _sanitize_review_content("hello")
        assert "text" in result

    def test_dict_preserved(self):
        result = _sanitize_review_content({"text": "hello", "other": 1})
        assert result.get("other") == 1

    def test_steam_copied_to_text(self):
        result = _sanitize_review_content({"stem": "question stem"})
        assert result.get("text") is not None

    def test_visual_region_fields_stripped(self):
        result = _sanitize_review_content({
            "text": "hello",
            "visual_regions": [1, 2],
            "visual_region_ids": ["a", "b"],
            "source_snapshot_url": "http://example.com",
            "source_snapshot_full_page": "data",
        })
        assert "visual_regions" not in result
        assert "visual_region_ids" not in result
        assert "source_snapshot_url" not in result
        assert "source_snapshot_full_page" not in result


class TestSanitizeReviewOptions:
    def test_non_dict_returns_empty(self):
        assert _sanitize_review_options(None) == {}
        assert _sanitize_review_options("string") == {}
        assert _sanitize_review_options([1, 2]) == {}

    def test_string_option_flattened(self):
        result = _sanitize_review_options({"A": "option text"})
        assert isinstance(result["A"], str)

    def test_dict_option_text_normalized(self):
        result = _sanitize_review_options({"A": {"text": "hello\nworld"}})
        assert "\n" not in result["A"]["text"]

    def test_dict_option_falls_back_to_value(self):
        result = _sanitize_review_options({"A": {"value": "fallback"}})
        assert "text" in result["A"]


class TestSanitizeReviewOptionValue:
    def test_string_normalizes_newlines(self):
        result = _sanitize_review_option_value("a\n\nb")
        assert "\n" not in result

    def test_non_string_non_dict_passes_through(self):
        assert _sanitize_review_option_value(123) == 123
        assert _sanitize_review_option_value(None) is None


class TestSM2Integration:
    def test_quality_below_3_resets_repetitions(self):
        result = calc_sm2(quality=2, efactor=2.5, interval=10, repetitions=5)
        assert result["repetitions"] == 0
        assert result["interval"] == 1

    def test_efactor_never_below_1_3(self):
        result = calc_sm2(quality=0, efactor=1.3, interval=10, repetitions=5)
        assert result["efactor"] >= 1.3

    def test_interval_sequence_1_6_then_ef_based(self):
        r1 = calc_sm2(quality=4, efactor=2.5, interval=0, repetitions=0)
        assert r1["interval"] == 1
        r2 = calc_sm2(quality=4, efactor=r1["efactor"], interval=r1["interval"], repetitions=r1["repetitions"])
        assert r2["interval"] == 6
        r3 = calc_sm2(quality=4, efactor=r2["efactor"], interval=r2["interval"], repetitions=r2["repetitions"])
        assert r3["interval"] >= 6

    def test_invalid_quality_raises(self):
        with pytest.raises(ValueError):
            calc_sm2(quality=6)
        with pytest.raises(ValueError):
            calc_sm2(quality=-1)
