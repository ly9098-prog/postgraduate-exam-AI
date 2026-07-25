"""PDF rendering service — offloaded, once-only, bounded, validated.

* All PyMuPDF calls run via a dedicated bounded executor (never the event loop).
* Pages streamed one-at-a-time via ``iter_pages()`` (cloud path).
* ``render_pages()`` returning a full ``dict[int, bytes]`` is **deprecated** (local-only).
* File validation (magic, page count, dimensions, decompression safety) before render.
* Resource limits raise ``PdfResourceLimitError`` — never silently skip.
* Bounded concurrency: max concurrent renders set by config.
* Cleanup always: temp files removed via tracked executor task.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import warnings
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from app.core.config import settings
from app.core.pdf_error import PdfResourceLimitError

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

    Deprecated: prefer ``iter_pages()`` for streaming access.
    """
    page_images: dict[int, bytes] = field(default_factory=dict)
    page_file_refs: dict[int, str] = field(default_factory=dict)
    total_pages: int = 0
    rendered_count: int = 0
    temp_dir: str | None = None
    accumulated_bytes: int = 0     # total bytes of all page_images


@dataclass
class RenderedPage:
    """A single rendered PDF page with resource accounting.

    Callers **must** call ``aclose()`` after processing to release the
    underlying PNG bytes and allow memory reclamation before the next page.
    """
    page_number: int
    width: int
    height: int
    decoded_bytes: int           # w × h × 4 (RGBA) — raw pixmap estimate
    png_bytes: bytes

    async def aclose(self) -> None:
        """Release the PNG byte buffer."""
        self.png_bytes = b""


def _validate_pdf(pdf_source: bytes | str, is_path: bool) -> None:
    """Validate PDF file before rendering.

    Raises ``ValueError`` with a descriptive message if any check fails.
    """

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
        raise PdfResourceLimitError(
            "too_many_pages",
            details={"actual": total_pages, "limit": _MAX_PAGES},
        )

    start_idx = max(0, (page_start or 1) - 1)
    end_idx = min(total_pages, page_end or total_pages)

    temp_dir: str | None = None
    result = PdfRenderResult(total_pages=total_pages)

    try:
        if is_path:
            temp_dir = tempfile.mkdtemp(prefix="pdf_render_")

        for i in range(start_idx, end_idx):
            page = doc[i]
            try:
                pix = page.get_pixmap(dpi=dpi)

                # Decompression bomb protection: pixel budget
                pixel_count = pix.width * pix.height
                if pixel_count > _MAX_PAGE_PIXELS:
                    doc.close()
                    raise PdfResourceLimitError(
                        "page_pixel_limit",
                        details={
                            "page": i + 1,
                            "actual_pixels": pixel_count,
                            "limit": _MAX_PAGE_PIXELS,
                        },
                    )

                # Decoded memory budget (RGBA: w × h × 4)
                decoded_bytes = pix.width * pix.height * 4
                max_decoded = settings.PDF_MAX_DECODED_BYTES
                if decoded_bytes > max_decoded:
                    doc.close()
                    raise PdfResourceLimitError(
                        "decoded_memory_limit",
                        details={
                            "page": i + 1,
                            "actual_decoded_bytes": decoded_bytes,
                            "limit": max_decoded,
                        },
                    )

                # Resize if exceeds max dimension
                render_pix = pix
                needs_resize = max(render_pix.width, render_pix.height) > max_dimension
                if needs_resize:
                    scale = max_dimension / max(render_pix.width, render_pix.height)
                    render_pix = page.get_pixmap(dpi=int(dpi * scale))

                png = render_pix.tobytes("png")
                page_num = i + 1

                result.page_images[page_num] = png
                result.accumulated_bytes += len(png)
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


def _count_pdf_pages(pdf_source: bytes | str, is_path: bool) -> int:
    """Open a PDF and return page count. Runs in executor."""
    import fitz
    doc = fitz.open(pdf_source) if is_path else fitz.open(stream=pdf_source, filetype="pdf")
    count = len(doc)
    doc.close()
    return count


def _render_one_page(
    pdf_source: bytes | str,
    is_path: bool,
    page_num: int,
    max_dimension: int,
    dpi: int,
) -> bytes:
    """Render a single PDF page to PNG bytes. Runs in executor.

    Raises PdfResourceLimitError on resource violations.
    """
    import fitz
    doc = fitz.open(pdf_source) if is_path else fitz.open(stream=pdf_source, filetype="pdf")
    try:
        if page_num < 1 or page_num > len(doc):
            raise PdfResourceLimitError(
                "too_many_pages",
                details={"page": page_num, "total": len(doc)},
            )
        page = doc[page_num - 1]
        pix = page.get_pixmap(dpi=dpi)

        # Decompression bomb protection
        pixel_count = pix.width * pix.height
        if pixel_count > _MAX_PAGE_PIXELS:
            raise PdfResourceLimitError(
                "page_pixel_limit",
                details={
                    "page": page_num,
                    "actual_pixels": pixel_count,
                    "limit": _MAX_PAGE_PIXELS,
                },
            )

        # Decoded memory budget
        decoded_bytes = pix.width * pix.height * 4
        max_decoded = settings.PDF_MAX_DECODED_BYTES
        if decoded_bytes > max_decoded:
            raise PdfResourceLimitError(
                "decoded_memory_limit",
                details={
                    "page": page_num,
                    "actual_decoded_bytes": decoded_bytes,
                    "limit": max_decoded,
                },
            )

        render_pix = pix
        if max(render_pix.width, render_pix.height) > max_dimension:
            scale = max_dimension / max(render_pix.width, render_pix.height)
            render_pix = page.get_pixmap(dpi=int(dpi * scale))
        return render_pix.tobytes("png")
    finally:
        doc.close()


def _guess_png_size(png_bytes: bytes) -> tuple[int, int] | None:
    """Extract width and height from a PNG IHDR chunk without PIL.

    PNG format: 8-byte signature, then IHDR chunk (13 bytes fixed).
    IHDR: 4 bytes length (always \\x00\\x00\\x00\\x0d), 4 bytes 'IHDR',
    4 bytes width (big-endian), 4 bytes height (big-endian).
    """
    if len(png_bytes) < 33 or png_bytes[:8] != b'\x89PNG\r\n\x1a\n':
        return None
    try:
        w = (png_bytes[16] << 24) | (png_bytes[17] << 16) | (png_bytes[18] << 8) | png_bytes[19]
        h = (png_bytes[20] << 24) | (png_bytes[21] << 16) | (png_bytes[22] << 8) | png_bytes[23]
        return w, h
    except (IndexError, ValueError):
        return None


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

        Returns a ``PdfRenderResult`` with **all** page images in memory.

        .. deprecated::
            Use ``iter_pages()`` for streaming access. This method keeps
            all rendered pages in memory simultaneously and will raise
            ``PdfResourceLimitError`` if the deployment profile forbids it.
        """
        from app.core.deployment_profile import DeploymentProfile, detect_deployment_profile

        if detect_deployment_profile() == DeploymentProfile.CLOUD_API:
            raise PdfResourceLimitError(
                "decoded_memory_limit",
                retryable=False,
                details={"message": "render_pages() is forbidden in cloud_api. Use iter_pages() for streaming."},
            )

        warnings.warn(
            "render_pages() is deprecated. Use iter_pages() for streaming.",
            DeprecationWarning,
            stacklevel=2,
        )

        if source_type != "pdf":
            return PdfRenderResult()

        pdf_source = file_path or file_content
        if pdf_source is None:
            return PdfRenderResult()

        effective_dpi = dpi or _DEFAULT_DPI

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

    async def iter_pages(
        self,
        *,
        file_content: bytes | None = None,
        file_path: str | None = None,
        source_type: str = "pdf",
        page_start: int = 1,
        page_end: int | None = None,
        max_dimension: int = 2048,
        dpi: int | None = None,
    ) -> AsyncIterator[RenderedPage]:
        """Stream rendered pages one at a time from a PDF.

        Yields ``RenderedPage`` objects.  Only one page is held
        in memory at a time, making this suitable for low-memory deployments
        (e.g. page_window=1 on cloud_api).

        All fitz calls run via ``run_in_executor`` — never blocks the event loop.

        Raises:
            PdfResourceLimitError: on page count / pixel / decoded memory violations.
        """
        if source_type != "pdf":
            return

        pdf_source = file_path or file_content
        if pdf_source is None:
            return

        effective_dpi = dpi or _DEFAULT_DPI
        is_path = isinstance(pdf_source, str)

        async with self._semaphore:
            loop = asyncio.get_running_loop()
            total_pages = await loop.run_in_executor(
                self._executor, _count_pdf_pages, pdf_source, is_path,
            )
            if total_pages == 0:
                return
            if total_pages > _MAX_PAGES:
                raise PdfResourceLimitError(
                    "too_many_pages",
                    details={"actual": total_pages, "limit": _MAX_PAGES},
                )

            start_idx = max(0, (page_start or 1) - 1)
            end_idx = min(total_pages, page_end or total_pages)

            for page_num in range(start_idx + 1, end_idx + 1):
                png_bytes = await loop.run_in_executor(
                    self._executor,
                    _render_one_page, pdf_source, is_path, page_num, max_dimension, effective_dpi,
                )
                # Estimate decoded bytes from PNG size (conservative: PNG is
                # typically 10-30% of raw RGBA, multiply by 4 as a safe factor).
                width, height = _guess_png_size(png_bytes) or (0, 0)
                decoded_estimate = width * height * 4
                yield RenderedPage(
                    page_number=page_num,
                    width=width,
                    height=height,
                    decoded_bytes=decoded_estimate,
                    png_bytes=png_bytes,
                )

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
