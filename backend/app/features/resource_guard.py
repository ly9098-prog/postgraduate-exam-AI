"""Resource Guard — 2C/2G production resource protection.

Enforces per-request and per-pipeline budgets for the cloud_api profile.
All limits are checked before work begins, not retroactively.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.core.deployment_profile import DeploymentProfile

logger = logging.getLogger(__name__)


class ResourceGuardError(ValueError):
    """Raised when a resource guard limit is exceeded."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


# ── Error Codes ────────────────────────────────────────────────────────────

INPUT_TOO_LARGE = "INPUT_TOO_LARGE"
PAGE_LIMIT_EXCEEDED = "PAGE_LIMIT_EXCEEDED"
PIXEL_BUDGET_EXCEEDED = "PIXEL_BUDGET_EXCEEDED"
CONCURRENCY_LIMIT_EXCEEDED = "CONCURRENCY_LIMIT_EXCEEDED"
REMOTE_OCR_CALL_BUDGET_EXCEEDED = "REMOTE_OCR_CALL_BUDGET_EXCEEDED"
ARTIFACT_SIZE_LIMIT_EXCEEDED = "ARTIFACT_SIZE_LIMIT_EXCEEDED"
PIPELINE_TIMEOUT = "PIPELINE_TIMEOUT"
PAGE_TIMEOUT = "PAGE_TIMEOUT"


@dataclass
class ResourceGuard:
    """Per-pipeline resource guard for cloud_api production profile.

    Guards are checked at pipeline start. If a guard is exceeded,
    the pipeline fails with a clear error code — no silent truncation.

    Fields are mutable counters; use ``check_*`` methods.
    """

    # ── Fixed limits ──
    max_input_bytes: int = 100 * 1024 * 1024
    max_pages: int = 200
    max_pixel_budget: int = 4000 * 4000 * 200  # 16 MP per page × 200 pages
    max_concurrent_documents: int = 1
    max_concurrent_pages: int = 1
    max_remote_ocr_calls: int = 100
    max_artifact_bytes: int = 100 * 1024 * 1024
    max_pipeline_seconds: int = 3600
    max_page_seconds: int = 300

    # ── Mutable state ──
    _render_pixels_consumed: int = 0
    _remote_ocr_calls: int = 0
    _artifact_bytes_written: int = 0
    _active_concurrent_documents: int = 0
    _active_concurrent_pages: int = 0

    @classmethod
    def for_profile(cls, profile: DeploymentProfile) -> ResourceGuard:
        """Create a ResourceGuard with defaults matching the deployment profile."""
        if profile == DeploymentProfile.CLOUD_API:
            return cls(
                max_input_bytes=10 * 1024 * 1024,  # 10 MB
                max_pages=50,
                max_pixel_budget=4000 * 4000 * 50,
                max_concurrent_documents=1,
                max_concurrent_pages=1,
                max_remote_ocr_calls=100,
                max_artifact_bytes=50 * 1024 * 1024,
                max_pipeline_seconds=1800,
                max_page_seconds=120,
            )
        # local_import: generous defaults
        return cls(
            max_input_bytes=200 * 1024 * 1024,
            max_pages=600,
            max_pixel_budget=4000 * 4000 * 600,
            max_concurrent_documents=1,
            max_concurrent_pages=3,
            max_remote_ocr_calls=500,
            max_artifact_bytes=500 * 1024 * 1024,
            max_pipeline_seconds=7200,
            max_page_seconds=600,
        )

    # ── Check methods ──

    def check_input_bytes(self, size: int) -> None:
        if size > self.max_input_bytes:
            raise ResourceGuardError(
                INPUT_TOO_LARGE,
                f"Input {size} bytes exceeds limit {self.max_input_bytes}",
            )

    def check_page_count(self, count: int) -> None:
        if count > self.max_pages:
            raise ResourceGuardError(
                PAGE_LIMIT_EXCEEDED,
                f"Page count {count} exceeds limit {self.max_pages}",
            )

    def check_render_pixels(self, pixels: int) -> None:
        new_total = self._render_pixels_consumed + pixels
        if new_total > self.max_pixel_budget:
            raise ResourceGuardError(
                PIXEL_BUDGET_EXCEEDED,
                f"Render pixel budget {new_total} exceeds limit {self.max_pixel_budget}",
            )
        self._render_pixels_consumed = new_total

    def check_concurrent_documents(self) -> None:
        if self._active_concurrent_documents >= self.max_concurrent_documents:
            raise ResourceGuardError(
                CONCURRENCY_LIMIT_EXCEEDED,
                f"Concurrent document limit {self.max_concurrent_documents} reached",
            )

    def check_concurrent_pages(self) -> None:
        if self._active_concurrent_pages >= self.max_concurrent_pages:
            raise ResourceGuardError(
                CONCURRENCY_LIMIT_EXCEEDED,
                f"Concurrent page limit {self.max_concurrent_pages} reached",
            )

    def check_remote_ocr_call(self) -> None:
        if self._remote_ocr_calls >= self.max_remote_ocr_calls:
            raise ResourceGuardError(
                REMOTE_OCR_CALL_BUDGET_EXCEEDED,
                f"Remote OCR calls {self._remote_ocr_calls} exceeds limit {self.max_remote_ocr_calls}",
            )
        self._remote_ocr_calls += 1

    def check_artifact_bytes(self, size: int) -> None:
        new_total = self._artifact_bytes_written + size
        if new_total > self.max_artifact_bytes:
            raise ResourceGuardError(
                ARTIFACT_SIZE_LIMIT_EXCEEDED,
                f"Artifact size {new_total} exceeds limit {self.max_artifact_bytes}",
            )
        self._artifact_bytes_written = new_total

    # ── Context managers for concurrency tracking ──

    def acquire_document(self) -> "_DocumentLease":
        self.check_concurrent_documents()
        self._active_concurrent_documents += 1
        return _DocumentLease(self)

    def acquire_page(self) -> "_PageLease":
        self.check_concurrent_pages()
        self._active_concurrent_pages += 1
        return _PageLease(self)


class _DocumentLease:
    def __init__(self, guard: ResourceGuard):
        self._guard = guard

    def release(self) -> None:
        self._guard._active_concurrent_documents -= 1


class _PageLease:
    def __init__(self, guard: ResourceGuard):
        self._guard = guard

    def release(self) -> None:
        self._guard._active_concurrent_pages -= 1
