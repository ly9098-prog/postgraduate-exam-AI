"""Reject OCR results whose page identity cannot be bound to the rendered batch."""

from __future__ import annotations

from typing import Any


def validate_scanned_results(
    batch_images: list[tuple[int, bytes]], results: dict[int, Any]
) -> None:
    if not isinstance(results, dict):
        raise ValueError("OCR batch results must be a page mapping")
    expected = {page for page, _ in batch_images}
    if any(type(page) is not int for page in results) or set(results) != expected:
        raise ValueError("OCR batch result pages must match the rendered batch")
    for page, result in results.items():
        actual_page = getattr(result, "page_index", None)
        if type(actual_page) is not int or actual_page != page:
            raise ValueError("OCR batch result identity must match its rendered page")
