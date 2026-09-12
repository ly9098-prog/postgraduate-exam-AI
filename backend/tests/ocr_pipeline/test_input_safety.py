"""Tests for Phase 3: InputSafetyValidator."""
from __future__ import annotations

from app.features.input_safety import InputSafetyValidator


class TestInputSafetyValidator:
    def setup_method(self):
        self.validator = InputSafetyValidator()

    def test_valid_pdf_passes(self):
        result = self.validator.validate(
            b"%PDF-1.4 some content here",
            filename="doc.pdf",
            mime="application/pdf",
        )
        assert result.passed

    def test_empty_source_fails(self):
        result = self.validator.validate(b"", filename="empty.pdf")
        assert not result.passed
        assert any("empty" in e.lower() for e in result.errors)

    def test_source_too_large(self):
        result = self.validator.validate(
            b"x" * (101 * 1024 * 1024),
            filename="large.pdf",
        )
        assert not result.passed
        assert any("too large" in e.lower() for e in result.errors)

    def test_magic_bytes_mismatch(self):
        result = self.validator.validate(
            b"not a pdf at all",
            filename="doc.pdf",
            mime="application/pdf",
        )
        assert not result.passed
        assert any("magic" in e.lower() for e in result.errors)

    def test_malicious_filename(self):
        result = self.validator.validate(
            b"%PDF-1.4 safe content",
            filename="../../etc/passwd",
        )
        assert not result.passed

    def test_path_traversal_detected(self):
        result = self.validator.validate(
            b"%PDF-1.4 safe content",
            filename="../outside.pdf",
        )
        assert not result.passed

    def test_pdf_pages_valid(self):
        result = self.validator.validate_pdf_pages(10)
        assert result.passed
        assert result.page_count == 10

    def test_pdf_pages_exceed_limit(self):
        result = self.validator.validate_pdf_pages(600)
        assert not result.passed

    def test_pdf_pages_invalid(self):
        result = self.validator.validate_pdf_pages(0)
        assert not result.passed

    def test_image_dimensions_valid(self):
        result = self.validator.validate_image_dimensions(800, 600)
        assert result.passed

    def test_image_dimensions_too_large(self):
        result = self.validator.validate_image_dimensions(30000, 30000)
        assert not result.passed

    def test_image_dimensions_too_small(self):
        result = self.validator.validate_image_dimensions(5, 5)
        assert not result.passed

    def test_image_pixel_budget_exceeded(self):
        result = self.validator.validate_image_dimensions(20000, 10000)
        assert not result.passed
        assert any("pixel" in e.lower() for e in result.errors)
