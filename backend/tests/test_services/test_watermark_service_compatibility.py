"""Real compatibility baseline for watermark matching and pattern validation."""

from __future__ import annotations

import re

import pytest

from app.services.watermark_service import (
    _validate_pattern,
    get_default_patterns,
    match_watermark,
)


class TestMatchWatermark:
    def test_empty_text_returns_false(self):
        assert match_watermark("", [re.compile("test")]) is False

    def test_whitespace_only_returns_false(self):
        assert match_watermark("   ", [re.compile("test")]) is False

    def test_matching_pattern_returns_true(self):
        assert match_watermark("仅供参考", get_default_patterns()) is True

    def test_non_matching_text_returns_false(self):
        assert match_watermark("正常题目内容", get_default_patterns()) is False

    def test_page_number_pattern_matches(self):
        assert match_watermark("第 3 页 / 共 10 页", get_default_patterns()) is True

    def test_multiple_patterns_first_match(self):
        pats = [re.compile("foo"), re.compile("bar")]
        assert match_watermark("bar text", pats) is True

    def test_no_patterns_returns_false(self):
        assert match_watermark("text", []) is False


class TestValidatePattern:
    def test_valid_pattern_accepted(self):
        _validate_pattern(r"^\d+$")

    def test_too_long_pattern_rejected(self):
        with pytest.raises(ValueError, match="过长"):
            _validate_pattern("a" * 201)

    def test_nested_quantifier_rejected(self):
        with pytest.raises(ValueError, match="ReDoS"):
            _validate_pattern(r"(a+)+")

    def test_invalid_regex_rejected(self):
        with pytest.raises(ValueError, match="无效"):
            _validate_pattern(r"[")

    def test_simple_pattern_accepted(self):
        _validate_pattern("watermark")


class TestGetDefaultPatterns:
    def test_returns_compiled_patterns(self):
        patterns = get_default_patterns()
        assert len(patterns) > 0
        for p in patterns:
            assert isinstance(p, re.Pattern)

    def test_patterns_match_known_watermarks(self):
        patterns = get_default_patterns()
        assert match_watermark("版权所有", patterns) is True
        assert match_watermark("内部资料", patterns) is True
        assert match_watermark("绝密", patterns) is True
        assert match_watermark("第 1 页", patterns) is True
        assert match_watermark("共 5 页", patterns) is True
