"""Real compatibility baseline for coverage service image anomaly detection.

Exercises the pure ``_image_ref_from_value`` and ``_has_image_reference_anomaly``
functions that detect malformed persisted image references without remote I/O.
"""

from __future__ import annotations

import pytest

from app.services.coverage_service import (
    _has_image_reference_anomaly,
    _image_ref_from_value,
)


class TestImageRefFromValue:
    def test_string_url_valid(self):
        assert _image_ref_from_value("https://cdn/img.png") == (True, True)

    def test_string_url_empty(self):
        assert _image_ref_from_value("") == (True, False)

    def test_string_url_whitespace(self):
        assert _image_ref_from_value("  ") == (True, False)

    def test_dict_with_url_key(self):
        assert _image_ref_from_value({"url": "https://cdn/img.png"}) == (True, True)

    def test_dict_with_empty_url(self):
        assert _image_ref_from_value({"url": ""}) == (True, False)

    def test_dict_with_src_key(self):
        assert _image_ref_from_value({"src": "https://cdn/img.png"}) == (True, True)

    def test_dict_without_image_keys(self):
        assert _image_ref_from_value({"text": "hello"}) == (True, False)

    def test_non_string_non_dict(self):
        assert _image_ref_from_value(123) == (True, False)
        assert _image_ref_from_value(None) == (True, False)


class TestHasImageReferenceAnomaly:
    def test_clean_content_no_anomaly(self):
        assert _has_image_reference_anomaly(
            {"text": "hello"}, None, None
        ) is False

    def test_image_segment_with_valid_url(self):
        assert _has_image_reference_anomaly(
            {"segments": [{"type": "image", "url": "https://cdn/img.png"}]},
            None, None,
        ) is False

    def test_image_segment_with_empty_url(self):
        assert _has_image_reference_anomaly(
            {"segments": [{"type": "image", "url": ""}]},
            None, None,
        ) is True

    def test_image_segment_with_missing_url(self):
        assert _has_image_reference_anomaly(
            {"segments": [{"type": "image"}]},
            None, None,
        ) is True

    def test_non_image_segment_ignored(self):
        assert _has_image_reference_anomaly(
            {"segments": [{"type": "text", "url": ""}]},
            None, None,
        ) is False

    def test_hidden_image_segment_ignored(self):
        assert _has_image_reference_anomaly(
            {"segments": [{"type": "image", "display": False, "url": ""}]},
            None, None,
        ) is False

    def test_image_url_list_with_valid_entries(self):
        assert _has_image_reference_anomaly(
            None, None, ["https://cdn/img.png"],
        ) is False

    def test_image_url_not_list(self):
        assert _has_image_reference_anomaly(
            None, None, "https://cdn/img.png",
        ) is True

    def test_image_url_list_with_invalid_entry(self):
        assert _has_image_reference_anomaly(
            None, None, ["valid.png", ""],
        ) is True

    def test_options_with_valid_image_url(self):
        assert _has_image_reference_anomaly(
            None,
            {"A": {"text": "opt", "image_url": "https://cdn/img.png"}},
            None,
        ) is False

    def test_options_with_empty_image_url(self):
        assert _has_image_reference_anomaly(
            None,
            {"A": {"text": "opt", "image_url": ""}},
            None,
        ) is True

    def test_math_image_segment_type(self):
        assert _has_image_reference_anomaly(
            {"segments": [{"type": "math_image", "url": ""}]},
            None, None,
        ) is True

    def test_table_image_segment_type(self):
        assert _has_image_reference_anomaly(
            {"segments": [{"type": "table_image", "url": ""}]},
            None, None,
        ) is True
