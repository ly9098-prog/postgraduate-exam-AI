"""Real compatibility baseline for AI import helper pure functions."""

from __future__ import annotations

import pytest

from app.services.ai_import_helpers import (
    extract_json,
    normalize_enrich,
)


class TestExtractJson:
    def test_empty_returns_none(self):
        assert extract_json("") is None
        assert extract_json(None) is None

    def test_plain_json(self):
        assert extract_json('{"key": "value"}') == {"key": "value"}

    def test_markdown_fenced(self):
        assert extract_json('```json\n{"key": 1}\n```') == {"key": 1}

    def test_text_around_json(self):
        assert extract_json('result: {"a": 1} done') == {"a": 1}

    def test_invalid_returns_none(self):
        assert extract_json("not json at all") is None


class TestNormalizeEnrich:
    def test_empty_dict_returns_empty(self):
        assert normalize_enrich({}) == {}

    def test_valid_subject_kept(self):
        result = normalize_enrich({"subject": "math2"})
        assert result["subject"] == "math2"

    def test_invalid_subject_dropped(self):
        result = normalize_enrich({"subject": "nonexistent"})
        assert "subject" not in result

    def test_valid_type_kept(self):
        result = normalize_enrich({"question_type": "choice"})
        assert result["question_type"] == "choice"

    def test_invalid_type_dropped(self):
        result = normalize_enrich({"question_type": "unknown"})
        assert "question_type" not in result

    def test_difficulty_in_range(self):
        result = normalize_enrich({"difficulty": 3})
        assert result["difficulty"] == 3

    def test_difficulty_out_of_range_dropped(self):
        result = normalize_enrich({"difficulty": 0})
        assert "difficulty" not in result
        result = normalize_enrich({"difficulty": 10})
        assert "difficulty" not in result

    def test_knowledge_points_filtered(self):
        result = normalize_enrich({"knowledge_points": ["kp1", "", "  ", "kp2"]})
        assert result["knowledge_points"] == ["kp1", "kp2"]

    def test_confidence_clamped(self):
        assert normalize_enrich({"confidence": 0.5})["confidence"] == 0.5
        assert normalize_enrich({"confidence": 1.5})["confidence"] == 1.0
        assert normalize_enrich({"confidence": -0.5})["confidence"] == 0.0

    def test_chapter_trimmed(self):
        result = normalize_enrich({"chapter": "  chapter1  "})
        assert result["chapter"] == "chapter1"

    def test_unknown_keys_dropped(self):
        result = normalize_enrich({"unknown_field": "value"})
        assert "unknown_field" not in result
