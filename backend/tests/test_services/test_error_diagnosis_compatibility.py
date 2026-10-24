"""Real compatibility baseline for error diagnosis taxonomy and normalization.

Exercises the pure taxonomy, normalization and serialization contracts.
No database needed — all deterministic pure functions.
"""

from __future__ import annotations

import pytest

from app.services.error_diagnosis_service import (
    ERROR_TYPES,
    LEGACY_TYPE_MAP,
    normalize_error_type,
    normalize_secondary_types,
    taxonomy_items,
)


class TestTaxonomyItems:
    def test_returns_all_types(self):
        items = taxonomy_items()
        assert len(items) == len(ERROR_TYPES)
        types = [item["type"] for item in items]
        assert set(types) == set(ERROR_TYPES)

    def test_each_item_has_label_and_description(self):
        for item in taxonomy_items():
            assert "type" in item
            assert "label" in item
            assert "description" in item
            assert isinstance(item["label"], str)
            assert isinstance(item["description"], str)


class TestNormalizeErrorType:
    @pytest.mark.parametrize("value,expected", [
        ("knowledge_gap", "knowledge_gap"),
        ("concept_confusion", "concept_confusion"),
        ("careless", "careless"),
        ("unknown", "unknown"),
    ])
    def test_canonical_types(self, value, expected):
        assert normalize_error_type(value) == expected

    @pytest.mark.parametrize("legacy,canonical", [
        ("concept_mistake", "concept_confusion"),
        ("concept", "concept_confusion"),
        ("calculation", "calculation_error"),
        ("memory", "memory_error"),
        ("method", "reasoning_error"),
        ("logic", "reasoning_error"),
        ("other", "unknown"),
        ("", "unknown"),
    ])
    def test_legacy_mapping(self, legacy, canonical):
        assert normalize_error_type(legacy) == canonical

    def test_unknown_value_returns_unknown(self):
        assert normalize_error_type("nonexistent_type") == "unknown"

    def test_none_returns_unknown(self):
        assert normalize_error_type(None) == "unknown"

    def test_disallow_unknown_raises(self):
        with pytest.raises(ValueError, match="unsupported"):
            normalize_error_type("nonexistent", allow_unknown=False)

    def test_disallow_unknown_allows_canonical(self):
        assert normalize_error_type("careless", allow_unknown=False) == "careless"


class TestNormalizeSecondaryTypes:
    def test_non_list_returns_empty(self):
        assert normalize_secondary_types("string") == []
        assert normalize_secondary_types(None) == []

    def test_deduplicates(self):
        result = normalize_secondary_types(["careless", "careless", "misread"])
        assert result.count("careless") == 1

    def test_excludes_primary(self):
        result = normalize_secondary_types(["careless", "misread"], primary="careless")
        assert "careless" not in result
        assert "misread" in result

    def test_excludes_unknown(self):
        result = normalize_secondary_types(["unknown", "careless"])
        assert "unknown" not in result
        assert "careless" in result

    def test_limits_to_3(self):
        types = ["knowledge_gap", "concept_confusion", "memory_error", "calculation_error", "misread"]
        result = normalize_secondary_types(types)
        assert len(result) <= 3

    def test_legacy_types_normalized(self):
        result = normalize_secondary_types(["concept_mistake", "calculation"])
        assert "concept_confusion" in result
        assert "calculation_error" in result


class TestLegacyTypeMap:
    def test_all_canonical_types_self_map(self):
        for t in ERROR_TYPES:
            assert LEGACY_TYPE_MAP.get(t, t) == t

    def test_empty_string_maps_to_unknown(self):
        assert LEGACY_TYPE_MAP[""] == "unknown"
