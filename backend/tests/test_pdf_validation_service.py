"""Tests for pdf_validation_service.py — all layers of PDF validation."""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.core.deployment_profile import DeploymentProfile
from app.services.pdf_validation_service import (
    PdfValidationError,
    _effective_limits,
    effective_page_window,
    validate_pdf,
    validate_pdf_basic,
)

# ── Fake PDF helpers ─────────────────────────────────────────────────────────


def _make_fake_pdf(page_count: int = 1, extra: bytes = b"") -> bytes:
    """Generate a minimal valid PDF with the requested page count.

    Uses a simple PDF structure that PyMuPDF can open.
    """
    pages = b""
    for i in range(page_count):
        pages += (
            b"  %d 0 obj\n<< /Type /Page /Parent 1 0 R /MediaBox [0 0 612 792] "
            b"/Contents 3 0 R >>\nendobj\n" % (2 + i)
        )
    content = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Pages /Kids ["
        + b" ".join(b"%d 0 R" % (2 + i) for i in range(page_count))
        + b"] /Count %d >>\nendobj\n" % page_count
        + pages
        + b"3 0 obj\n<< /Length 44 >>\nstream\nBT /F1 12 Tf 100 700 Td (Hello) Tj ET\nendstream\nendobj\n"
        b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n"
        + b"\n".join(b"%010d 00000 n " % (100 + i * 50) for i in range(page_count + 2))
        + b"\ntrailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n200\n%%%%EOF\n"
    )
    return content + extra


def _make_fake_png() -> bytes:
    """Minimal valid PNG."""
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


# ── Test effective limits ───────────────────────────────────────────────────


class TestEffectiveLimits:
    def test_cloud_limits_stricter(self):
        with patch(
            "app.services.pdf_validation_service.detect_deployment_profile",
            return_value=DeploymentProfile.CLOUD_API,
        ):
            limits = _effective_limits()
            assert limits["page_window"] == 1
            assert limits["max_pages"] <= 30

    def test_local_limits_looser(self):
        with patch(
            "app.services.pdf_validation_service.detect_deployment_profile",
            return_value=DeploymentProfile.LOCAL_IMPORT,
        ):
            limits = _effective_limits()
            # local uses the larger config value
            assert limits["max_file_bytes"] == settings.PDF_MAX_FILE_SIZE_BYTES


# ── Test validate_pdf_basic (no PyMuPDF) ────────────────────────────────────


class TestValidateBasic:
    def test_valid_pdf_bytes(self):
        pdf = _make_fake_pdf()
        result = validate_pdf_basic(pdf)
        assert result["file_bytes"] == len(pdf)

    def test_invalid_magic_bytes(self):
        data = b"not a PDF"
        with pytest.raises(PdfValidationError, match="magic bytes"):
            validate_pdf_basic(data)

    def test_file_too_large(self):
        limits = _effective_limits()
        big_data = b"%PDF-1.4\n" + b"x" * limits["max_file_bytes"]
        with pytest.raises(PdfValidationError, match="过大"):
            validate_pdf_basic(big_data)

    def test_file_path_valid(self, tmp_path):
        pdf = _make_fake_pdf()
        p = tmp_path / "test.pdf"
        p.write_bytes(pdf)
        result = validate_pdf_basic(str(p), is_path=True)
        assert result["file_bytes"] == len(pdf)

    def test_file_path_not_found(self):
        with pytest.raises(PdfValidationError, match="not found"):
            validate_pdf_basic("/nonexistent/file.pdf", is_path=True)

    def test_empty_bytes(self):
        with pytest.raises(PdfValidationError, match="magic bytes"):
            validate_pdf_basic(b"")


# ── Test validate_pdf_deep (requires PyMuPDF) ───────────────────────────────


class TestValidateDeep:
    """These tests need PyMuPDF to actually open the PDF."""

    @pytest.mark.skipif(
        not os.environ.get("FULL_TEST"),
        reason="PyMuPDF-dependent — set FULL_TEST=1 to run",
    )
    def test_valid_pdf_deep(self):
        pdf = _make_fake_pdf(page_count=3)
        result = validate_pdf(pdf, deep=True)
        assert result["page_count"] == 3

    def test_encrypted_pdf(self):
        """Encrypted PDF should fail deep validation."""
        try:
            import fitz
        except ImportError:
            pytest.skip("PyMuPDF not available")

        pdf = _make_fake_pdf()
        doc = fitz.open(stream=pdf, filetype="pdf")
        # PyMuPDF opens encrypted PDFs as empty — just check encryption detection
        # In practice, doc.is_encrypted will be True for real encrypted files
        # We test the code path by mocking
        from unittest.mock import patch as mock_patch

        with mock_patch("fitz.open") as mock_open:
            mock_doc = mock_open.return_value.__enter__.return_value
            mock_doc.is_encrypted = True
            mock_doc.__len__.return_value = 1
            from app.services.pdf_validation_service import validate_pdf_deep

            with pytest.raises(PdfValidationError, match="encrypted"):
                validate_pdf_deep(pdf)

    @pytest.mark.skipif(
        not os.environ.get("FULL_TEST"),
        reason="PyMuPDF-dependent — set FULL_TEST=1 to run",
    )
    def test_too_many_pages(self):
        pdf = _make_fake_pdf(page_count=100)
        with patch(
            "app.services.pdf_validation_service._effective_limits",
            return_value={
                "max_file_bytes": 200 * 1024 * 1024,
                "max_pages": 5,
                "max_page_pixels": 4096 * 4096,
                "total_pixel_budget": 4000 * 4000 * 30,
                "page_window": 1,
            },
        ):
            with pytest.raises(PdfValidationError, match="页数过多"):
                validate_pdf(pdf, deep=True)


# ── Test effective_page_window ──────────────────────────────────────────────


class TestEffectivePageWindow:
    def test_cloud_returns_one(self):
        with patch(
            "app.services.pdf_validation_service.detect_deployment_profile",
            return_value=DeploymentProfile.CLOUD_API,
        ):
            assert effective_page_window() == 1

    def test_local_returns_config(self):
        with patch(
            "app.services.pdf_validation_service.detect_deployment_profile",
            return_value=DeploymentProfile.LOCAL_IMPORT,
        ):
            w = effective_page_window()
            assert w >= 1


# ── Test validate_pdf convenience wrapper ───────────────────────────────────


class TestValidatePdf:
    def test_basic_by_default(self):
        pdf = _make_fake_pdf()
        result = validate_pdf(pdf)
        assert "file_bytes" in result

    def test_deep_flag(self):
        pdf = _make_fake_pdf(page_count=1)
        result = validate_pdf(pdf, deep=False)
        assert "file_bytes" in result
        # deep=False returns only basic info
