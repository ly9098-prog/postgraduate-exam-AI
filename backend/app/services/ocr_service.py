"""OCR service — 向后兼容包装器。

All OCR algorithm code has been MOVED to ``app.core.ocr_engine``.
This module provides backward-compatible wrappers that delegate to
``OCRGateway`` or the legacy executor service.

DO NOT add new OCR logic here. Use ``OCRGateway.recognize_pages()`` instead.
"""

from __future__ import annotations

import asyncio
import logging
import warnings

from app.core.ocr_types import OcrCandidateResult, OcrPageResult, WorkerResult

logger = logging.getLogger(__name__)


# ── Private helpers ─────────────────────────────────────────────────────────


def _get_gateway():
    """Get the OCRGateway singleton (lazy)."""
    try:
        from app.features.ocr_gateway import OCRGateway
        # Use a module-level singleton or create fresh
        return _gateway_singleton
    except ImportError:
        return None


# Module-level gateway singleton (set by main.py or first access)
_gateway_singleton = None


def set_gateway(gateway) -> None:
    """Set the global OCRGateway singleton (called from main.py on startup)."""
    global _gateway_singleton
    _gateway_singleton = gateway


def get_gateway():
    """Get the global OCRGateway singleton."""
    return _gateway_singleton


def _run_async(coro):
    """Run a coroutine from sync context."""
    try:
        loop = asyncio.get_running_loop()
        if loop.is_running():
            raise RuntimeError("Cannot run from event loop thread")
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


# ── Deprecated OCR functions ────────────────────────────────────────────────


def ocr_pages(page_images: list[tuple[int, bytes]]) -> dict[int, str]:
    """
    并发 OCR 多页。

    DEPRECATED: Use ``OCRGateway.recognize_pages()`` instead.
    """
    warnings.warn(
        "ocr_service.ocr_pages() is deprecated. "
        "Use OCRGateway.recognize_pages() instead.",
        DeprecationWarning, stacklevel=2,
    )

    if not page_images:
        return {}

    # Try Gateway
    gateway = get_gateway()
    if gateway is not None and gateway.is_gateway:
        try:
            results = _run_async(
                gateway.recognize_pages(page_images),
            )
            return {
                r.page_index: (r.result.get("text", "") if r.result else "")
                for r in results
            }
        except Exception as exc:
            logger.warning("Gateway OCR failed, falling back: %s", exc)

    # Fallback: executor service
    return _legacy_ocr_pages(page_images)


def ocr_pages_with_boxes(
    page_images: list[tuple[int, bytes]],
    skip_rotation: bool = False,
) -> dict[int, OcrPageResult]:
    """并发 OCR 多页，返回含检测框坐标的结果。

    DEPRECATED: Use ``OCRGateway.recognize_pages()`` instead.
    """
    warnings.warn(
        "ocr_service.ocr_pages_with_boxes() is deprecated. "
        "Use OCRGateway.recognize_pages() instead.",
        DeprecationWarning, stacklevel=2,
    )

    if not page_images:
        return {}

    # Try Gateway
    gateway = get_gateway()
    if gateway is not None and gateway.is_gateway:
        try:
            results = _run_async(
                gateway.recognize_pages(
                    page_images,
                ),
            )
            return {
                r.page_index: _worker_result_to_page_result(r)
                for r in results
            }
        except Exception as exc:
            logger.warning("Gateway OCR boxes failed, falling back: %s", exc)

    # Fallback: executor service
    return _legacy_ocr_pages_with_boxes(page_images, skip_rotation)


def ocr_raw_text(image_bytes: bytes) -> str:
    """Run OCR without preprocessing.

    DEPRECATED: Use ``OCRGateway.recognize_pages(mode="raw")`` instead.
    """
    warnings.warn(
        "ocr_service.ocr_raw_text() is deprecated.",
        DeprecationWarning, stacklevel=2,
    )

    gateway = get_gateway()
    if gateway is not None and gateway.is_gateway:
        try:
            results = _run_async(
                gateway.recognize_pages(
                    [(0, image_bytes)],
                ),
            )
            if results and results[0].result:
                return results[0].result.get("text", "")
        except Exception as exc:
            logger.warning("Gateway raw OCR failed, falling back: %s", exc)

    return _legacy_ocr_raw_text(image_bytes)


def reset_ocr_engine() -> None:
    """Reset OCR engine state — recycles the process pool workers.

    Call this after an OCR failure to force worker pool recreation.
    Next OCR call will spawn fresh workers with a clean PaddleOCR instance.
    """
    logger.info("reset_ocr_engine() called — recycling process pool workers")
    from app.core.ocr_process_pool import ocr_process_pool
    ocr_process_pool._shutdown_nonblocking()


def ocr_is_available() -> bool:
    """Check if OCR is available.

    Checks the Gateway's worker client for health.
    Works for both local process pool and PaddleX HTTP backends.
    """
    gateway = get_gateway()
    if gateway is not None:
        metrics = gateway.worker_metrics
        alive = metrics.get("alive_workers", 0)
        if alive > 0:
            return True
        # PaddleX HTTP backend doesn't have "alive_workers" key.
        # Check backend-specific reachability.
        backend = metrics.get("backend", "")
        if backend == "paddlex_http":
            return metrics.get("configured", False) and not metrics.get("reachable") is False
        return False
    return False


def get_ocr_init_error() -> str | None:
    """Return initialization error message."""
    return None  # Worker pool manages lifecycle; individual errors are per-task


# ── Utility functions (NOT deprecated) ──────────────────────────────────────


def clean_ocr_text(text: str, *, trace_id: str = "") -> str:
    """Clean OCR output text — delegates to text_normalizer.normalize_ocr_text()."""
    from app.features.text_normalizer import normalize_ocr_text
    return normalize_ocr_text(text, trace_id=trace_id)


def get_ocr_cache_stats() -> dict:
    """Return OCR cache hit/miss statistics."""
    try:
        from app.services.ocr_cache_service import get_stats
        return get_stats()
    except ImportError:
        return {"hits": 0, "misses": 0, "hit_rate": 0.0}


def get_last_transform_tracker():
    """Return the TransformTracker from the most recent OCR call.

    DEPRECATED: Transforms are now embedded in WorkerResult.
    """
    warnings.warn(
        "get_last_transform_tracker() is deprecated. "
        "Transforms are embedded in WorkerResult.",
        DeprecationWarning, stacklevel=2,
    )
    return None


# ── Internal: legacy fallback paths ─────────────────────────────────────────


def _legacy_ocr_pages(page_images: list[tuple[int, bytes]]) -> dict[int, str]:
    """Legacy OCR pages path via executor service."""
    from app.services.ocr_executor_service import ocr_executor

    try:
        return _run_async(ocr_executor.run_ocr_pages(page_images))
    except Exception as exc:
        logger.error("Legacy OCR pages failed: %s", exc)
        return {idx: "" for idx, _ in page_images}


def _legacy_ocr_pages_with_boxes(
    page_images: list[tuple[int, bytes]],
    skip_rotation: bool = False,
) -> dict[int, OcrPageResult]:
    """Legacy OCR pages with boxes path via executor service."""
    from app.services.ocr_executor_service import ocr_executor

    try:
        raw = _run_async(
            ocr_executor.run_ocr_pages_with_boxes(
                page_images, skip_rotation=skip_rotation,
            ),
        )
        result: dict[int, OcrPageResult] = {}
        for idx, _ in page_images:
            entry = raw.get(idx)
            if entry is None:
                result[idx] = OcrPageResult(page_index=idx, text="", boxes=[])
            elif isinstance(entry, dict):
                result[idx] = OcrPageResult(
                    page_index=entry.get("page_index", idx),
                    text=entry.get("text", ""),
                    boxes=entry.get("boxes", []),
                    failed=entry.get("failed", False),
                    error=entry.get("error"),
                )
            else:
                result[idx] = entry
        return result
    except Exception as exc:
        logger.error("Legacy OCR boxes failed: %s", exc)
        return {idx: OcrPageResult(page_index=idx, text="", boxes=[]) for idx, _ in page_images}


def _legacy_ocr_raw_text(image_bytes: bytes) -> str:
    """Legacy raw OCR path."""
    from app.core.ocr_process_pool import ocr_process_pool

    try:
        return ocr_process_pool.get_text(image_bytes, 0, timeout=60)
    except Exception as exc:
        logger.warning("Legacy raw OCR failed: %s", exc)
        return ""


def _worker_result_to_page_result(r) -> OcrPageResult:
    """Convert a WorkerResult (or similar) from Gateway to OcrPageResult."""
    if r is None:
        return OcrPageResult(page_index=0, text="", boxes=[], failed=True, error="No result")

    result_data = r.result if hasattr(r, "result") else r
    if isinstance(result_data, dict):
        return OcrPageResult(
            page_index=result_data.get("page_index", getattr(r, "page_index", 0)),
            text=result_data.get("text", ""),
            boxes=result_data.get("boxes", []),
            failed=result_data.get("failed", False),
            error=result_data.get("error"),
            transforms=result_data.get("transforms"),
        )

    return OcrPageResult(
        page_index=getattr(r, "page_index", 0),
        text="",
        boxes=[],
        failed=False,
    )
