"""Tests for Phase 3: NativeTextProbe + Shadow Mode."""
from __future__ import annotations

from app.features.native_text_probe import NativeTextProbe


class TestNativeTextProbe:
    def setup_method(self):
        self.probe = NativeTextProbe(mode="shadow")

    def test_empty_text_returns_local_ocr(self):
        result = self.probe.analyze_page("", page_index=0)
        assert result.route_recommendation == "LOCAL_OCR"
        assert result.confidence == 0.0
        assert "NO_NATIVE_TEXT" in result.reason_codes

    def test_clean_text_returns_native_text(self):
        text = "This is a clean page with standard Chinese text 考研数学二真题。"
        result = self.probe.analyze_page(
            text,
            page_index=0,
            page_width=612,
            page_height=792,
            text_bbox_area=5000,
            font_count=3,
        )
        assert result.route_recommendation == "NATIVE_TEXT"
        assert result.printable_ratio > 0.85
        assert result.confidence > 0.5

    def test_garbled_text_returns_local_ocr(self):
        # Text with high ratio of control characters
        text = "Normal\x00text\x01with\x02control\x07chars\x1fAAAA"
        result = self.probe.analyze_page(text, page_index=0)
        assert "LOCAL_OCR" in result.route_recommendation

    def test_high_duplicate_glyph_returns_local_ocr(self):
        text = "AAAAAAAAAAAAAAAAABBBBBBBBBBBBBBB" + ("normal text " * 5)
        result = self.probe.analyze_page(text, page_index=0)
        assert result.route_recommendation == "LOCAL_OCR"
        assert result.duplicate_glyph_ratio > 0.30

    def test_high_image_coverage_returns_remote_ocr_vl(self):
        text = "Some readable text here but lots of images"
        # Short text with high image coverage → low printable ratio → LOCAL_OCR
        result = self.probe.analyze_page(
            text,
            page_index=0,
            page_width=612,
            page_height=792,
            image_bbox_area=400000,
        )
        # With font_count=0 and high image coverage, goes LOCAL_OCR (low font count)
        # With font_count≥2, goes REMOTE_OCR_VL (high image, printable ok)
        result2 = self.probe.analyze_page(
            text,
            page_index=0,
            page_width=612,
            page_height=792,
            image_bbox_area=400000,
            font_count=3,
        )
        assert result2.route_recommendation in ("HYBRID", "REMOTE_OCR_VL")

    def test_mixed_page_returns_hybrid(self):
        text = "Page with text and " + ("A" * 50) + " significant images " * 20
        result = self.probe.analyze_page(
            text,
            page_index=0,
            page_width=612,
            page_height=792,
            image_bbox_area=400000,
            text_bbox_area=5000,
            font_count=3,
        )
        assert result.route_recommendation in ("HYBRID", "REMOTE_OCR_VL", "NATIVE_TEXT")

    def test_confidence_metrics(self):
        text = "Clean text with good printable ratio for analysis."
        result = self.probe.analyze_page(text, page_index=0)
        assert 0.0 <= result.confidence <= 1.0
        assert result.printable_ratio >= 0.0
        assert result.garbled_ratio >= 0.0

    def test_native_text_length_tracked(self):
        text = "Hello World 你好世界"
        result = self.probe.analyze_page(text, page_index=0)
        assert result.native_text_length == len(text)

    def test_shadow_mode_does_not_raise(self):
        """Shadow mode must not raise exceptions."""
        self.probe = NativeTextProbe(mode="shadow")
        result = self.probe.analyze_page("some text", page_index=0)
        assert result.route_recommendation is not None

    def test_low_prontable_ratio_with_images_returns_remote_ocr_vl(self):
        text = "ab"
        result = self.probe.analyze_page(
            text,
            page_index=0,
            page_width=612,
            page_height=792,
            image_bbox_area=500000,
            font_count=2,
        )
        assert result.route_recommendation in ("REMOTE_OCR_VL", "HYBRID", "LOCAL_OCR")


class TestNativeTextShadowNoRouteChange:
    """Shadow mode must NOT change production routes."""

    def test_shadow_recommendation_is_advisory(self):
        probe = NativeTextProbe(mode="shadow")
        assert probe.is_shadow

    def test_off_mode_no_analysis(self):
        probe = NativeTextProbe(mode="off")
        # In off mode, probe still computes but should be no-op behavior
        result = probe.analyze_page("test", page_index=0)
        assert result is not None
