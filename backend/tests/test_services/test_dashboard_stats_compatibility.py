"""Real compatibility baseline for dashboard/stats pure normalization functions.

Exercises ``_extract_json_object``, ``_normalize_text_list`` and
``_normalize_dashboard_actions`` — deterministic pure functions that sanitize
AI provider output before it reaches the API/UI.
"""

from __future__ import annotations

import pytest

from app.services.stats_service import (
    _extract_json_object,
    _normalize_dashboard_actions,
    _normalize_text_list,
)


class TestExtractJsonObject:
    def test_empty_returns_none(self):
        assert _extract_json_object("") is None
        assert _extract_json_object(None) is None

    def test_plain_json(self):
        result = _extract_json_object('{"key": "value"}')
        assert result == {"key": "value"}

    def test_markdown_wrapped(self):
        result = _extract_json_object('```json\n{"key": 1}\n```')
        assert result == {"key": 1}

    def test_text_around_json(self):
        result = _extract_json_object('Here is the result: {"a": 1} done.')
        assert result == {"a": 1}

    def test_invalid_json_returns_none(self):
        assert _extract_json_object("{broken") is None

    def test_array_returns_none(self):
        """Only dict objects are accepted, not arrays."""
        assert _extract_json_object("[1, 2, 3]") is None

    def test_nested_object(self):
        result = _extract_json_object('{"outer": {"inner": true}}')
        assert result == {"outer": {"inner": True}}


class TestNormalizeTextList:
    def test_non_list_returns_empty(self):
        assert _normalize_text_list("string", limit=5) == []
        assert _normalize_text_list(None, limit=5) == []

    def test_filters_non_strings(self):
        result = _normalize_text_list(["a", 123, None, "b"], limit=5)
        assert result == ["a", "b"]

    def test_filters_empty_strings(self):
        result = _normalize_text_list(["a", "", "  ", "b"], limit=5)
        assert result == ["a", "b"]

    def test_truncates_to_limit(self):
        result = _normalize_text_list(["a", "b", "c"], limit=2)
        assert result == ["a", "b"]

    def test_truncates_long_text(self):
        result = _normalize_text_list(["x" * 300], limit=5)
        assert len(result[0]) == 240


class TestNormalizeDashboardActions:
    def test_non_list_returns_empty(self):
        assert _normalize_dashboard_actions(None) == []
        assert _normalize_dashboard_actions("string") == []

    def test_filters_non_dict(self):
        assert _normalize_dashboard_actions(["string", 123]) == []

    def test_valid_action(self):
        result = _normalize_dashboard_actions([
            {"type": "review", "title": "复习错题", "desc": "建议复习"},
        ])
        assert len(result) == 1
        assert result[0]["type"] == "review"
        assert result[0]["title"] == "复习错题"

    def test_invalid_type_filtered(self):
        result = _normalize_dashboard_actions([
            {"type": "invalid", "title": "test"},
        ])
        assert result == []

    def test_missing_title_filtered(self):
        result = _normalize_dashboard_actions([
            {"type": "review", "desc": "no title"},
        ])
        assert result == []

    def test_truncates_title_and_desc(self):
        result = _normalize_dashboard_actions([
            {"type": "practice", "title": "x" * 200, "desc": "y" * 300},
        ])
        assert len(result[0]["title"]) == 80
        assert len(result[0]["desc"]) == 220

    def test_limit_default_4(self):
        items = [{"type": "review", "title": f"t{i}"} for i in range(10)]
        result = _normalize_dashboard_actions(items)
        assert len(result) == 4

    def test_type_normalized_to_lowercase(self):
        result = _normalize_dashboard_actions([
            {"type": "REVIEW", "title": "test"},
        ])
        assert result[0]["type"] == "review"
