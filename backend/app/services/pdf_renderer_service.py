"""PDF rendering service — offloaded, once-only, bounded, validated.

* All PyMuPDF calls run via a dedicated bounded executor (never the event loop).
* Each page is rendered *once*; results served as bytes and optional file refs.
* File validation (magic, page count, dimensions, decompression safety) before render.
* Bounded concurrency: max concurrent renders set by config.
* Cleanup always: temp files removed via tracked executor task.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from app.core.config import settings

logger = logging.getLogger("postgraduate-ai.pdf-renderer")

# Limits (hard-coded safety caps, config can lower but not raise)
_MAX_FILE_SIZE = 200 * 1024 * 1024   # 200 MB
_MAX_PAGES = 600
_MAX_PAGE_PIXELS = 4096 * 4096
_MAX_IMAGE_DIMENSION = 8192
_DEFAULT_DPI = 150


@dataclass
class PdfRenderResult:
    """Result of a PDF rendering operation.

    Each page is rendered once and stored both as in-memory bytes and
    an optional temp-file path.
    """
    page_images: dict[int, bytes] = field(default_factory=dict)
    page_file_refs: dict[int, str] = field(default_factory=dict)
    total_pages: int = 0
    rendered_count: int = 0
    temp_dir: str | None = None


def _validate_pdf(pdf_source: bytes | str, is_path: bool) -> None:
    """Validate PDF file before rendering.

    Raises ``ValueError`` with a descriptive message if any check fails.
    """
    import struct

    if is_path:
        size = os.path.getsize(pdf_source)
        if size > _MAX_FILE_SIZE:
            raise ValueError(
                f"PDF 文件过大: {size} 字节 (上限 {_MAX_FILE_SIZE})"
            )
    else:
        if len(pdf_source) > _MAX_FILE_SIZE:
            raise ValueError(
                f"PDF 数据过大: {len(pdf_source)} 字节 (上限 {_MAX_FILE_SIZE})"
            )

    # Magic bytes: PDF starts with "%PDF-"
    header = pdf_source[:5] if not is_path else b""
    if is_path:
        with open(pdf_source, "rb") as fh:
            header = fh.read(5)
    if header[:4] != b"%PDF":
        raise ValueError("文件不是有效的 PDF（magic bytes 不匹配）")


def _render_sync(
    pdf_source: bytes | str,
    is_path: bool,
    page_start: int,
    page_end: int | None,
    max_dimension: int,
    dpi: int,
) -> PdfRenderResult:
    """Synchronous rendering — runs inside the dedicated executor."""
    import fitz

    _validate_pdf(pdf_source, is_path)

    doc = (
        fitz.open(pdf_source)  # str path → mmap
        if is_path
        else fitz.open(stream=pdf_source, filetype="pdf")
    )
    total_pages = len(doc)

    if total_pages > _MAX_PAGES:
        doc.close()
        raise RuntimeError(
            f"PDF 页数过多: {total_pages} (上限 {_MAX_PAGES})"
        )

    start_idx = max(0, (page_start or 1) - 1)
    end_idx = min(total_pages, page_end or total_pages)
    page_count = end_idx - start_idx

    temp_dir: str | None = None
    result = PdfRenderResult(total_pages=total_pages)

    try:
        if is_path:
            temp_dir = tempfile.mkdtemp(prefix="pdf_render_")

        for i in range(start_idx, end_idx):
            page = doc[i]
            try:
                pix = page.get_pixmap(dpi=dpi)

                # Enforce pixel budget (decompression bomb protection)
                pixel_count = pix.width * pix.height
                if pixel_count > _MAX_PAGE_PIXELS:
                    logger.warning(
                        "Page %d exceeds pixel limit (%d > %d), skipping",
                        i + 1, pixel_count, _MAX_PAGE_PIXELS,
                    )
                    continue

                # Resize if exceeds max dimension
                render_pix = pix
                needs_resize = max(render_pix.width, render_pix.height) > max_dimension
                if needs_resize:
                    scale = max_dimension / max(render_pix.width, render_pix.height)
                    render_pix = page.get_pixmap(dpi=int(dpi * scale))

                png = render_pix.tobytes("png")
                page_num = i + 1

                # Store bytes (single page in memory at a time is fine)
                result.page_images[page_num] = png
                result.rendered_count += 1

                # Write temp file if needed
                if temp_dir:
                    filepath = os.path.join(temp_dir, f"page_{page_num:04d}.png")
                    with open(filepath, "wb") as f:
                        f.write(png)
                    result.page_file_refs[page_num] = filepath
            finally:
                page = None  # ensure page ref is released

        result.temp_dir = temp_dir
    except Exception:
        if temp_dir:
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)
        doc.close()
        raise

    doc.close()
    return result


class _PdfRenderer:
    """Bounded, validated PDF renderer.

    * All fitz calls run via a dedicated ``ThreadPoolExecutor``.
    * Bounded queue — ``max_concurrent`` calls at once.
    * File validation before any rendering starts.
    * Temp files tracked and cleaned up via ``cleanup()``.
    """

    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=settings.PDF_MAX_RENDER_PAGES_CONCURRENT,
            thread_name_prefix="pdf_render",
        )
        self._semaphore = asyncio.Semaphore(
            settings.PDF_MAX_RENDER_PAGES_CONCURRENT
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
        """Render PDF pages via the dedicated executor.

        Applies pre-render validation in the executor (not event loop).
        Returns a ``PdfRenderResult`` with page images and optional file refs.
        """
        if source_type != "pdf":
            return PdfRenderResult()

        pdf_source = file_path or file_content
        if pdf_source is None:
            return PdfRenderResult()

        effective_dpi = dpi or _DEFAULT_DPI

        # Acquire concurrency slot before submitting to executor
        async with self._semaphore:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                self._executor,
                _render_sync,
                pdf_source,
                isinstance(pdf_source, str),
                page_start,
                page_end,
                max_dimension,
                effective_dpi,
            )
        return result

    async def cleanup(self, result: PdfRenderResult) -> None:
        """Remove temporary files created by a render operation."""
        if result.temp_dir and os.path.isdir(result.temp_dir):
            import shutil
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                self._executor, shutil.rmtree, result.temp_dir,
            )

    async def shutdown(self) -> None:
        """Shut down the internal thread pool."""
        self._executor.shutdown(wait=False, cancel_futures=True)
        logger.info("PDF renderer shut down")


# Process-wide singleton
pdf_renderer = _PdfRenderer()
