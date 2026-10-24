"""Real compatibility baseline for visual region type helpers."""

from __future__ import annotations

import pytest

from app.services.visual_region_types import (
    VISUAL_BLOCKING_FLAGS,
    contains_visual_reference,
    get_blocking_risk_flags,
    make_image_segment,
    make_math_image_segment,
    make_newline_segment,
    make_text_segment,
)


class TestContainsVisualReference:
    def test_none_returns_false(self):
        assert contains_visual_reference(None) is False

    def test_empty_returns_false(self):
        assert contains_visual_reference("") is False

    def test_plain_text_returns_false(self):
        assert contains_visual_reference("hello world") is False

    def test_visual_reference_returns_true(self):
        assert contains_visual_reference("如图所示") is True


class TestGetBlockingRiskFlags:
    def test_empty_list_returns_empty(self):
        assert get_blocking_risk_flags([]) == []

    def test_non_blocking_flags_filtered(self):
        result = get_blocking_risk_flags(["source_snapshot_failed", "some_other_flag"])
        assert "source_snapshot_failed" not in result

    def test_blocking_flags_kept(self):
        flags = ["visual_crop_failed", "visual_region_ambiguous"]
        result = get_blocking_risk_flags(flags)
        assert set(result) == set(flags)

    def test_mixed_flags(self):
        flags = ["visual_crop_failed", "source_snapshot_failed", "visual_region_bbox_missing"]
        result = get_blocking_risk_flags(flags)
        assert "visual_crop_failed" in result
        assert "visual_region_bbox_missing" in result
        assert "source_snapshot_failed" not in result


class TestSegmentBuilders:
    def test_make_text_segment(self):
        seg = make_text_segment("hello")
        assert seg["type"] == "text"
        assert seg["text"] == "hello"

    def test_make_newline_segment(self):
        seg = make_newline_segment()
        assert seg["type"] == "newline"

    def test_make_image_segment_minimal(self):
        seg = make_image_segment("https://cdn/img.png")
        assert seg["type"] == "image"
        assert seg["url"] == "https://cdn/img.png"
        assert seg["display"] is True

    def test_make_image_segment_with_options(self):
        seg = make_image_segment("url", alt="diagram", region_id="r1", option_key="A")
        assert seg["alt"] == "diagram"
        assert seg["region_id"] == "r1"
        assert seg["option_key"] == "A"

    def test_make_math_image_segment(self):
        seg = make_math_image_segment("url", requires_review=False)
        assert seg["type"] == "math_image"
        assert seg["requires_review"] is False

    def test_make_math_image_segment_none_url(self):
        seg = make_math_image_segment(None)
        assert seg["url"] is None
        assert seg["requires_review"] is True
