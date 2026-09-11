"""Unified PDF validation service — file-level checks before rendering.

Separated from ``pdf_renderer_service.py`` so callers can validate PDFs
before enqueuing (no PyMuPDF import at enqueue time for the basic checks).

Basic checks (no PyMuPDF needed):
- Magic bytes, file size, MIME-like header
Extended checks (requires PyMuPDF, runs in executor):
- Page count, page dimensions, encryption, compression ratio

Limits vary by deployment profile (cloud vs local).
"""

from __future__ import annotations

import logging
import os
from typing import Any

from app.core.config import settings
from app.core.deployment_profile import DeploymentProfile, detect_deployment_profile

logger = logging.getLogger(__name__)


class PdfValidationError(ValueError):
    """Raised when a PDF fails validation."""

    def __init__(
        self, message: str, *, code: str = "", details: dict | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


# ── Limit helpers ────────────────────────────────────────────────────────────


def _effective_limits() -> dict[str, int]:
    """Return validation limits appropriate for the current deployment profile."""
    profile = detect_deployment_profile()
    is_cloud = profile == DeploymentProfile.CLOUD_API

    return {
        "max_file_bytes": settings.PDF_MAX_FILE_BYTES
        if is_cloud
        else settings.PDF_MAX_FILE_SIZE_BYTES,
        "max_pages": settings.PDF_MAX_PAGES
        if not is_cloud
        else min(settings.PDF_MAX_PAGES, 30),
        "max_page_pixels": settings.PDF_MAX_PAGE_PIXELS,
        "total_pixel_budget": settings.PDF_TOTAL_PIXEL_BUDGET,
        "page_window": 1 if is_cloud else max(1, settings.PDF_RENDER_PAGE_WINDOW),
    }


# ── Level 1: Basic checks (no PyMuPDF) ──────────────────────────────────────


def validate_pdf_basic(
    pdf_source: bytes | str, is_path: bool = False
) -> dict[str, int]:
    """Validate PDF without opening it — magic bytes, file size, returns size.

    Returns:
        ``{"file_bytes": int}`` on success.

    Raises:
        PdfValidationError on any failed check.
    """
    limits = _effective_limits()

    if is_path:
        if not os.path.isfile(pdf_source):
            raise PdfValidationError(
                f"PDF file not found: {pdf_source}",
                code="not_found",
            )
        size = os.path.getsize(pdf_source)
        if size > limits["max_file_bytes"]:
            raise PdfValidationError(
                f"PDF 文件过大: {size} bytes (上限 {limits['max_file_bytes']})",
                code="file_too_large",
                details={"actual_bytes": size, "limit": limits["max_file_bytes"]},
            )
        header = _read_header(pdf_source)
    else:
        size = len(pdf_source)
        if size > limits["max_file_bytes"]:
            raise PdfValidationError(
                f"PDF 数据过大: {size} bytes (上限 {limits['max_file_bytes']})",
                code="file_too_large",
                details={"actual_bytes": size, "limit": limits["max_file_bytes"]},
            )
        header = pdf_source[:5]

    if header[:4] != b"%PDF":
        raise PdfValidationError(
            "文件不是有效的 PDF（magic bytes 不匹配）",
            code="bad_magic",
            details={"header": header[:8].hex() if header else ""},
        )

    return {"file_bytes": size}


def _read_header(path: str) -> bytes:
    """Read the first 5 bytes of a file."""
    with open(path, "rb") as f:
        return f.read(5)


# ── Level 2: Extended checks (requires PyMuPDF) ─────────────────────────────


def validate_pdf_deep(pdf_source: bytes | str, is_path: bool = False) -> dict[str, Any]:
    """Open the PDF with PyMuPDF and run extended checks.

    Must be called from a thread executor (PyMuPDF is not async-safe).

    Returns:
        ``{"page_count": int, "file_bytes": int}`` on success.

    Raises:
        PdfValidationError on any failed check.
    """
    import fitz

    basic = validate_pdf_basic(pdf_source, is_path)
    limits = _effective_limits()

    doc = (
        fitz.open(pdf_source)
        if is_path
        else fitz.open(stream=pdf_source, filetype="pdf")
    )

    try:
        # Check encryption
        if doc.is_encrypted:
            raise PdfValidationError(
                "PDF is encrypted — cannot process",
                code="encrypted",
            )

        page_count = len(doc)
        if page_count > limits["max_pages"]:
            raise PdfValidationError(
                f"PDF 页数过多: {page_count} (上限 {limits['max_pages']})",
                code="too_many_pages",
                details={"actual_pages": page_count, "limit": limits["max_pages"]},
            )

        # Check each page's dimensions, total pixel budget
        total_pixels = 0
        for i in range(page_count):
            page = doc[i]
            rect = page.rect
            w, h = int(rect.width), int(rect.height)

            pixels = w * h
            if pixels > limits["max_page_pixels"]:
                raise PdfValidationError(
                    f"Page {i + 1} pixel count {pixels} exceeds limit "
                    f"{limits['max_page_pixels']}",
                    code="page_pixel_limit",
                    details={
                        "page": i + 1,
                        "width": w,
                        "height": h,
                        "actual_pixels": pixels,
                        "limit": limits["max_page_pixels"],
                    },
                )
            total_pixels += pixels

        if total_pixels > limits["total_pixel_budget"]:
            raise PdfValidationError(
                f"Total pixel budget exceeded: {total_pixels} "
                f"(上限 {limits['total_pixel_budget']})",
                code="total_pixel_budget",
                details={
                    "actual_pixels": total_pixels,
                    "limit": limits["total_pixel_budget"],
                },
            )

        # Compression ratio sanity: compare file size to raw pixel estimate
        raw_estimate = total_pixels * 4  # RGBA bytes
        file_bytes = basic["file_bytes"]
        ratio = raw_estimate / max(file_bytes, 1)
        if ratio < 1.5:
            logger.warning(
                "PDF compression ratio suspiciously low: file=%d bytes, "
                "raw_estimate=%d bytes, ratio=%.2f",
                file_bytes,
                raw_estimate,
                ratio,
            )

        return {
            "page_count": page_count,
            "file_bytes": file_bytes,
            "total_pixels": total_pixels,
            "page_dimensions_summary": _page_dimensions_summary(doc),
        }
    finally:
        doc.close()


def _page_dimensions_summary(doc) -> list[dict]:
    """Return a compact summary of page dimensions for logging."""
    summary = []
    for i in range(min(len(doc), 5)):
        r = doc[i].rect
        summary.append({"page": i + 1, "w": int(r.width), "h": int(r.height)})
    if len(doc) > 5:
        summary.append({"more_pages": len(doc) - 5})
    return summary


# ── Convenience wrapper ──────────────────────────────────────────────────────


def validate_pdf(
    pdf_source: bytes | str,
    is_path: bool = False,
    *,
    deep: bool = False,
) -> dict[str, Any]:
    """Run basic (+ optional deep) PDF validation.

    Args:
        pdf_source: File path (str) or bytes content.
        is_path: Whether ``pdf_source`` is a file path.
        deep: If True, also run PyMuPDF-level checks (page count,
            dimensions, encryption). Must be called from a thread
            executor when ``deep=True``.

    Returns:
        Dict with validation result metadata.
    """
    if deep:
        return validate_pdf_deep(pdf_source, is_path=is_path)
    return validate_pdf_basic(pdf_source, is_path=is_path)


def effective_page_window() -> int:
    """Return the effective page window size for the current profile.

    Cloud: always 1 (single-page window).
    Local: ``PDF_RENDER_PAGE_WINDOW`` or default 3.
    """
    profile = detect_deployment_profile()
    if profile == DeploymentProfile.CLOUD_API:
        return 1
    return max(1, settings.PDF_RENDER_PAGE_WINDOW or 3)
