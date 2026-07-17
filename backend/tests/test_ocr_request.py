"""OCRRequest tests — input validation, limits, type safety."""
from __future__ import annotations

import pytest

from app.core.ocr_request import OCRRequest


class TestOCRRequestConstruction:
    """Valid construction and type inference."""

    def test_minimal_pdf_request(self):
        req = OCRRequest(source=b"fake-pdf-content", source_type="pdf")
        assert req.source_type == "pdf"
        assert req.mime == "application/pdf"
        assert len(req.source_sha256) == 64  # SHA256 hex

    def test_png_request_infers_mime(self):
        req = OCRRequest(source=b"fake-png", source_type="png")
        assert req.mime == "image/png"

    def test_explicit_mime(self):
        req = OCRRequest(source=b"data", source_type="jpeg", mime="image/jpeg")
        assert req.mime == "image/jpeg"

    def test_page_range_defaults(self):
        req = OCRRequest(source=b"data", source_type="pdf")
        assert req.page_start == 1
        assert req.page_end is None

    def test_client_hash_preserved(self):
        req = OCRRequest(source=b"data", source_type="pdf", client_hash="abc123")
        assert req.client_hash == "abc123"


class TestOCRRequestValidation:
    """Invalid input rejection."""

    def test_rejects_non_bytes_source(self):
        with pytest.raises(ValueError, match="must be bytes"):
            OCRRequest(source="string-path", source_type="pdf")  # type: ignore

    def test_rejects_empty_source(self):
        with pytest.raises(ValueError, match="must not be empty"):
            OCRRequest(source=b"", source_type="pdf")

    def test_rejects_unsupported_source_type(self):
        with pytest.raises(ValueError, match="source_type must be one of"):
            OCRRequest(source=b"data", source_type="docx")

    def test_rejects_unsupported_mime(self):
        with pytest.raises(ValueError, match="mime must be one of"):
            OCRRequest(source=b"data", source_type="pdf", mime="text/plain")

    def test_rejects_negative_page_start(self):
        with pytest.raises(ValueError, match="page_start must be >= 1"):
            OCRRequest(source=b"data", source_type="pdf", page_start=0)

    def test_rejects_page_end_before_start(self):
        with pytest.raises(ValueError, match="page_end.*must be >= page_start"):
            OCRRequest(source=b"data", source_type="pdf", page_start=3, page_end=2)

    def test_rejects_excessive_page_range(self):
        with pytest.raises(ValueError, match="exceeds max_pages"):
            OCRRequest(source=b"data", source_type="pdf", page_start=1, page_end=300, max_pages=200)

    def test_rejects_excessive_size(self):
        with pytest.raises(ValueError, match="exceeds max_bytes"):
            OCRRequest(source=b"x" * 1001, source_type="pdf", max_bytes=1000)


class TestOCRRequestDescribe:
    """Human-readable description."""

    def test_describe_pdf(self):
        req = OCRRequest(source=b"content", source_type="pdf", filename="test.pdf")
        desc = req.describe()
        assert "pdf" in desc
        assert "test.pdf" in desc

    def test_describe_with_page_range(self):
        req = OCRRequest(source=b"content", source_type="pdf", page_start=2, page_end=5)
        desc = req.describe()
        assert "p2-5" in desc


class TestOCRRequestHashing:
    """SHA256 computation."""

    def test_sha256_is_deterministic(self):
        req1 = OCRRequest(source=b"hello", source_type="pdf")
        req2 = OCRRequest(source=b"hello", source_type="pdf")
        assert req1.source_sha256 == req2.source_sha256

    def test_sha256_changes_with_content(self):
        req1 = OCRRequest(source=b"hello", source_type="pdf")
        req2 = OCRRequest(source=b"world", source_type="pdf")
        assert req1.source_sha256 != req2.source_sha256
