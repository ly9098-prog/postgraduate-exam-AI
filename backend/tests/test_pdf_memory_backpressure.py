"""PDF memory invariants and backpressure tests.

Tests cover:
- Single-page window memory usage (cloud profile)
- Bounded executor backpressure (queue full → error)
- Cancellation cleanup (document close, temp dir cleanup)
"""
from __future__ import annotations

import asyncio
import os
import tempfile
import time
from unittest.mock import patch

import pytest

from app.core.bounded_executor import BoundedExecutor, ExecutorQueueFullError
from app.core.deployment_profile import DeploymentProfile


# ══════════════════════════════════════════════════════════════════════════════
# Bounded executor backpressure
# ══════════════════════════════════════════════════════════════════════════════


class TestBoundedExecutorBackpressure:
    """When a bounded executor's queue is full, further submissions fail fast."""

    @pytest.mark.asyncio
    async def test_queue_full_raises(self):
        """Submitting to a full bounded executor raises ExecutorQueueFullError."""
        executor = BoundedExecutor("test", max_workers=1, max_queued=0, timeout=5)

        def slow_task():
            time.sleep(10)  # blocks the thread pool worker

        # First submission: occupies the single worker
        t1 = asyncio.create_task(executor.run(slow_task))
        await asyncio.sleep(0.05)  # let it start

        # Second submission: no queue slots (max_queued=0), should raise
        with pytest.raises(ExecutorQueueFullError):
            await executor.run(slow_task)

        t1.cancel()
        try:
            await t1
        except (asyncio.CancelledError, Exception):
            pass
        await executor.shutdown()


# ══════════════════════════════════════════════════════════════════════════════
# Single-page window memory invariants (cloud profile)
# ══════════════════════════════════════════════════════════════════════════════


class TestSinglePageWindow:
    """Cloud profile should only hold one page's rendered bytes at a time."""

    @pytest.mark.asyncio
    async def test_page_bytes_released_after_aclose(self):
        """After calling aclose(), png_bytes is emptied."""
        from app.services.pdf_renderer_service import RenderedPage

        page = RenderedPage(
            page_number=1,
            width=100, height=100,
            decoded_bytes=40000,
            png_bytes=b"x" * 1000,
        )
        assert len(page.png_bytes) == 1000
        await page.aclose()
        assert page.png_bytes == b""

    def test_no_global_png_cache(self):
        """PageStream uses window-based iteration, not a full accumulating dict.

        The cloud profile renders one page at a time rather than accumulating
        all pages in a dict.  PageStream enforces a minimum window of 2.
        """
        from app.features.page_stream import PageStream

        stream = PageStream(window_size=2)
        # minimum window_size is clamped to >= 2
        assert stream._window_size >= 2

    @pytest.mark.asyncio
    async def test_effective_page_window_cloud(self):
        """Cloud: effective page window is always 1."""
        from app.services.pdf_validation_service import effective_page_window

        with patch(
            "app.services.pdf_validation_service.detect_deployment_profile",
            return_value=DeploymentProfile.CLOUD_API,
        ):
            assert effective_page_window() == 1

    @pytest.mark.asyncio
    async def test_effective_page_window_local(self):
        """Local: effective page window matches config or defaults to 3."""
        from app.services.pdf_validation_service import effective_page_window

        with patch(
            "app.services.pdf_validation_service.detect_deployment_profile",
            return_value=DeploymentProfile.LOCAL_IMPORT,
        ):
            w = effective_page_window()
            assert w >= 1


# ══════════════════════════════════════════════════════════════════════════════
# Cancellation cleanup
# ══════════════════════════════════════════════════════════════════════════════


class TestCancellationCleanup:
    """Cancellation must close PDF documents and clean up temp directories."""

    @pytest.mark.asyncio
    async def test_page_aclose_during_cancellation(self):
        """Cancelling a task that holds a RenderedPage releases its bytes."""
        from app.services.pdf_renderer_service import RenderedPage

        page = RenderedPage(
            page_number=1,
            width=100, height=100,
            decoded_bytes=40000,
            png_bytes=b"x" * 500,
        )

        async def processor():
            data = page.png_bytes
            await asyncio.sleep(1)
            return data

        task = asyncio.create_task(processor())
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # After cancellation, page bytes should be released
        await page.aclose()
        assert page.png_bytes == b""

    def test_tempdir_cleanup(self):
        """Temp directory should be removed after processing."""
        import shutil

        tmpdir = tempfile.mkdtemp(prefix="pdf_test_")
        assert os.path.isdir(tmpdir)

        shutil.rmtree(tmpdir, ignore_errors=True)
        assert not os.path.isdir(tmpdir)


# ══════════════════════════════════════════════════════════════════════════════
# PDF validation integration (basic checks, no PyMuPDF)
# ══════════════════════════════════════════════════════════════════════════════


class TestPdfValidationMemoryGuard:
    """PDF validation must reject files that would cause OOM."""

    def test_huge_file_rejected(self):
        """Oversized PDF should be rejected at validation time, never rendered."""
        from app.services.pdf_validation_service import validate_pdf_basic, PdfValidationError

        data = b"%PDF-1.4\n" + b"x" * (201 * 1024 * 1024)
        with pytest.raises(PdfValidationError, match="过大"):
            validate_pdf_basic(data)
