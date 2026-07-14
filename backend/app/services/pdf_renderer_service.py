"""PDF rendering service — offloaded, once-only, bounded.

Eliminates duplicate page rendering (each PDF page is rendered exactly once)
and keeps PyMuPDF off the asyncio event loop.

Usage::

    result = await pdf_renderer.render_pages(file_path=path, source_type="pdf")
    # result.page_images = {1: png_bytes, 2: png_bytes, ...}
    # result.page_file_refs = {1: "/tmp/.../page_1.png", ...}
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from app.core.config import settings

logger = logging.getLogger("postgraduate-ai.pdf-renderer")


@dataclass
class PdfRenderResult:
    """Result of a PDF rendering operation.

    Each page is rendered once and stored both as in-memory bytes and
    an optional temp-file path. Callers use whichever representation
    they need without triggering a second render pass.
    """
    page_images: dict[int, bytes] = field(default_factory=dict)
    page_file_refs: dict[int, str] = field(default_factory=dict)
    total_pages: int = 0
    rendered_count: int = 0
    temp_dir: str | None = None


class _PdfRenderer:
    """Process-wide, bounded PDF renderer.

    * All PyMuPDF calls run via ``asyncio.to_thread`` (never the event loop).
    * Each page is rendered *once*; the result is served as both bytes and file ref.
    * Configurable max file size, max pages, max pixel count, and DPI.
    * Temp files are tracked and cleaned up via ``cleanup()``.
    """

    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=settings.PDF_MAX_RENDER_PAGES_CONCURRENT,
            thread_name_prefix="pdf_render",
        )

    async def render_pages(
        self,
        *,
        file_content: bytes | None = None,
        file_path: str | None = None,
        source_type: str = "pdf",
        page_start: int = 1,
        page_end: int | None = None,
        max_dimension: int = 2048,
        dpi: int | None = None,
    ) -> PdfRenderResult:
        """Render PDF pages once, returning both bytes and temp-file refs.

        The rendering runs in a thread. Temp files are written to a single
        ``tempfile.mkdtemp()`` directory.
        """
        if source_type != "pdf":
            return PdfRenderResult()

        pdf_source = file_path or file_content
        if pdf_source is None:
            return PdfRenderResult()

        effective_dpi = dpi or settings.PDF_RENDER_DPI
        result = await asyncio.to_thread(
            self._render_sync,
            pdf_source=pdf_source,
            is_path=isinstance(pdf_source, str),
            page_start=page_start,
            page_end=page_end,
            max_dimension=max_dimension,
            dpi=effective_dpi,
        )
        return result

    def _render_sync(
        self,
        pdf_source: bytes | str,
        is_path: bool,
        page_start: int,
        page_end: int | None,
        max_dimension: int,
        dpi: int,
    ) -> PdfRenderResult:
        """Synchronous rendering — runs inside ``asyncio.to_thread``."""
        import fitz

        doc = (
            fitz.open(pdf_source)  # str path → mmap
            if is_path
            else fitz.open(stream=pdf_source, filetype="pdf")
        )
        total_pages = len(doc)

        if total_pages > settings.PDF_MAX_PAGES:
            doc.close()
            raise RuntimeError(
                f"PDF has {total_pages} pages, exceeding limit of {settings.PDF_MAX_PAGES}"
            )

        start_idx = max(0, (page_start or 1) - 1)
        end_idx = min(total_pages, page_end or total_pages)

        temp_dir: str | None = None
        result = PdfRenderResult(total_pages=total_pages)

        try:
            # Only create temp dir when file_path-based rendering is needed
            # (file refs are only used by math_detect stage)
            if isinstance(pdf_source, str):
                temp_dir = tempfile.mkdtemp(prefix="pdf_render_")

            for i in range(start_idx, end_idx):
                page = doc[i]
                pix = page.get_pixmap(dpi=dpi)

                # Enforce pixel budget
                if pix.width * pix.height > settings.PDF_MAX_PAGE_PIXELS:
                    logger.warning(
                        "Page %d exceeds pixel limit (%d > %d), skipping render",
                        i + 1, pix.width * pix.height, settings.PDF_MAX_PAGE_PIXELS,
                    )
                    continue

                # Resize if exceeds max dimension
                render_pix = pix
                if max(render_pix.width, render_pix.height) > max_dimension:
                    scale = max_dimension / max(render_pix.width, render_pix.height)
                    render_pix = page.get_pixmap(dpi=int(dpi * scale))

                png = render_pix.tobytes("png")

                # Store bytes
                page_num = i + 1
                result.page_images[page_num] = png
                result.rendered_count += 1

                # Write temp file if we have a temp dir
                if temp_dir:
                    filepath = os.path.join(temp_dir, f"page_{page_num:04d}.png")
                    with open(filepath, "wb") as f:
                        f.write(png)
                    result.page_file_refs[page_num] = filepath

            result.temp_dir = temp_dir
        except Exception:
            # Clean up temp dir on error
            if temp_dir:
                import shutil
                shutil.rmtree(temp_dir, ignore_errors=True)
            doc.close()
            raise

        doc.close()
        return result

    async def cleanup(self, result: PdfRenderResult) -> None:
        """Remove temporary files created by a render operation."""
        if result.temp_dir and os.path.isdir(result.temp_dir):
            import shutil
            await asyncio.to_thread(shutil.rmtree, result.temp_dir, ignore_errors=True)

    async def shutdown(self) -> None:
        """Shut down the internal thread pool."""
        self._executor.shutdown(wait=False, cancel_futures=True)
        logger.info("PDF renderer shut down")


# Process-wide singleton
pdf_renderer = _PdfRenderer()
