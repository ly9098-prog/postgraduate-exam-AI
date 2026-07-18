"""Unified OCR execution service — bounded executor + semaphore + queue limit + timeout.

All local OCR calls MUST go through this service instead of calling
``ocr_image`` / ``ocr_pages`` directly. This ensures:

- Sync OCR runs in dedicated threads (never blocks the event loop)
- Concurrent OCR is limited by a process-wide semaphore
- Queue overflow fast-fails with a clear error instead of memory exhaustion
- Timeouts are handled cleanly (marked, logged, never left hanging)
- The executor is properly shut down on application exit

Usage::

    from app.services.ocr_executor_service import ocr_executor

    text = await ocr_executor.run_ocr(image_bytes)
    pages = await ocr_executor.run_ocr_pages([(1, png1), (2, png2)])
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Any

from app.core.config import settings

logger = logging.getLogger("postgraduate-ai.ocr-executor")


class OcrQueueFullError(RuntimeError):
    """Raised when the OCR task queue has reached its capacity."""


class OcrTaskTimeoutError(RuntimeError):
    """Raised when an individual OCR task exceeds its timeout."""


class _OcrExecutorService:
    """Process-wide, bounded OCR executor.

    ``run_ocr`` and ``run_ocr_pages`` use ``OcrProcessPool`` (process isolation)
    by default when available, falling back to the thread pool.

    ``_run_in_executor`` provides the thread pool path with semaphore + timeout
    + done_callback for sync OCR wrappers (``ocr_service.ocr_pages_with_boxes``).
    """

    def __init__(self) -> None:
        self._executor: ThreadPoolExecutor | None = None
        self._semaphore: asyncio.Semaphore | None = None
        self._lock = threading.Lock()
        self._shutdown = False

        self._max_workers: int = settings.OCR_EXECUTOR_WORKERS
        self._max_concurrency: int = settings.OCR_MAX_CONCURRENCY
        self._max_queue_size: int = settings.OCR_MAX_QUEUE_SIZE
        self._task_timeout: int = settings.OCR_TASK_TIMEOUT_SEC

        self._running_tasks: dict[int, float] = {}
        self._total_submitted: int = 0
        self._total_completed: int = 0
        self._total_timed_out: int = 0
        self._total_queue_full: int = 0

    # --- lazy init ---------------------------------------------------------

    def _ensure_executor(self) -> tuple[ThreadPoolExecutor, asyncio.Semaphore]:
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=self._max_workers,
                thread_name_prefix="ocr_exec",
            )
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self._max_concurrency)
        return self._executor, self._semaphore

    def get_thread_pool(self) -> ThreadPoolExecutor:
        """Return the shared thread pool for sync OCR callers."""
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=self._max_workers,
                thread_name_prefix="ocr_exec",
            )
        return self._executor

    # --- public API (process-pool by default) -----------------------------

    async def run_ocr(
        self,
        image_bytes: bytes,
        timeout: int | None = None,
    ) -> str:
        """OCR a single image via process-isolated worker (fallback to thread pool)."""
        from app.services.ocr_service import ocr_image

        effective_timeout = timeout if timeout is not None else self._task_timeout
        try:
            from app.core.ocr_process_pool import ocr_process_pool

            loop = asyncio.get_event_loop()
            text = await asyncio.wait_for(
                loop.run_in_executor(
                    None, ocr_process_pool.get_text, image_bytes, 0, effective_timeout,
                ),
                timeout=effective_timeout + 10,
            )
            return text
        except ImportError:
            logger.debug("OCR process pool unavailable, falling back to thread pool")
            return await self._run_in_executor(ocr_image, image_bytes, timeout=timeout)

    async def run_ocr_pages(
        self,
        page_images: list[tuple[int, bytes]],
        timeout: int | None = None,
    ) -> dict[int, str]:
        """OCR multiple pages via process-isolated workers (fallback to thread pool)."""
        if not page_images:
            return {}

        try:
            from app.core.ocr_process_pool import ocr_process_pool

            effective_timeout = timeout if timeout is not None else self._task_timeout
            results: dict[int, str] = {}
            for idx, png in page_images:
                try:
                    text = await asyncio.wait_for(
                        asyncio.get_event_loop().run_in_executor(
                            None, ocr_process_pool.get_text, png, idx, effective_timeout,
                        ),
                        timeout=effective_timeout + 10,
                    )
                    results[idx] = text
                except Exception as exc:
                    logger.warning("OCR process-pool page %d failed: %s", idx, exc)
                    results[idx] = ""
            return results
        except ImportError:
            logger.debug("OCR process pool unavailable, falling back to thread pool")
            return await self._run_ocr_pages_threaded(page_images, timeout=timeout)

    async def run_ocr_pages_with_boxes(
        self,
        page_images: list[tuple[int, bytes]],
        skip_rotation: bool = False,
        timeout: int | None = None,
    ) -> dict[int, Any]:
        """OCR pages with detection boxes via process-isolated workers."""
        if not page_images:
            return {}

        effective_timeout = timeout if timeout is not None else self._task_timeout
        try:
            from app.core.ocr_process_pool import ocr_process_pool

            results: dict[int, Any] = {}
            for idx, png in page_images:
                try:
                    result = await asyncio.wait_for(
                        asyncio.get_event_loop().run_in_executor(
                            None, ocr_process_pool.get_text_with_boxes,
                            png, idx, skip_rotation, effective_timeout,
                        ),
                        timeout=effective_timeout + 10,
                    )
                    results[idx] = result
                except Exception as exc:
                    logger.warning("OCR process-pool boxed page %d failed: %s", idx, exc)
                    results[idx] = {
                        "page_index": idx, "text": "", "boxes": [],
                        "failed": True, "error": str(exc),
                    }
            return results
        except ImportError:
            logger.debug("OCR process pool unavailable, falling back to thread pool")
            return await self._run_ocr_boxes_threaded(
                page_images, skip_rotation=skip_rotation, timeout=timeout,
            )

    # --- backward-compat delegates ---------------------------------------

    async def run_ocr_pages_in_process(
        self,
        page_images: list[tuple[int, bytes]],
        timeout: int | None = None,
    ) -> dict[int, str]:
        """Delegate to ``run_ocr_pages`` (now process-pool by default)."""
        return await self.run_ocr_pages(page_images, timeout=timeout)

    async def run_ocr_pages_with_boxes_in_process(
        self,
        page_images: list[tuple[int, bytes]],
        skip_rotation: bool = False,
        timeout: int | None = None,
    ) -> dict[int, Any]:
        """Delegate to ``run_ocr_pages_with_boxes`` (now process-pool by default)."""
        return await self.run_ocr_pages_with_boxes(
            page_images, skip_rotation=skip_rotation, timeout=timeout,
        )

    # --- thread pool fallbacks -------------------------------------------

    async def _run_ocr_pages_threaded(
        self,
        page_images: list[tuple[int, bytes]],
        timeout: int | None = None,
    ) -> dict[int, str]:
        """OCR multiple pages through the bounded thread pool."""
        if not page_images:
            return {}

        from app.services.ocr_service import _ocr_one_page

        results: dict[int, str] = {}

        async def _ocr_one(png: bytes, idx: int) -> tuple[int, str | None]:
            try:
                _, text = await self._run_in_executor(
                    _ocr_one_page, png, idx, timeout=timeout,
                )
                return idx, text
            except Exception as exc:
                logger.warning("OCR page %d failed: %s", idx, exc)
                return idx, None

        tasks = [asyncio.create_task(_ocr_one(png, idx)) for idx, png in page_images]
        for coro in asyncio.as_completed(tasks):
            idx, text = await coro
            results[idx] = text if text is not None else ""
        return results

    async def _run_ocr_boxes_threaded(
        self,
        page_images: list[tuple[int, bytes]],
        skip_rotation: bool = False,
        timeout: int | None = None,
    ) -> dict[int, Any]:
        """OCR pages with boxes through the bounded thread pool."""
        if not page_images:
            return {}

        from app.services.ocr_service import _ocr_one_page_with_boxes

        results: dict[int, Any] = {}

        async def _ocr_one(png: bytes, idx: int) -> tuple[int, Any | None]:
            try:
                result = await self._run_in_executor(
                    _ocr_one_page_with_boxes, png, idx, skip_rotation,
                    timeout=timeout,
                )
                return idx, result
            except Exception as exc:
                logger.warning("OCR boxed page %d failed: %s", idx, exc)
                return idx, None

        tasks = [asyncio.create_task(_ocr_one(png, idx)) for idx, png in page_images]
        for coro in asyncio.as_completed(tasks):
            idx, result = await coro
            if result is not None:
                results[idx] = result
        return results

    # --- internal thread pool executor -----------------------------------

    async def _run_in_executor(
        self,
        fn: callable,
        *args: Any,
        timeout: int | None = None,
    ) -> Any:
        """Submit *fn(*args)* to the thread pool with semaphore and timeout."""
        if self._shutdown:
            raise RuntimeError("OCR executor is shut down")

        effective_timeout = timeout if timeout is not None else self._task_timeout

        pending = self._total_submitted - self._total_completed
        if pending >= self._max_queue_size:
            self._total_queue_full += 1
            raise OcrQueueFullError(
                f"OCR queue full ({pending} pending, max {self._max_queue_size})"
            )

        executor, semaphore = self._ensure_executor()
        await semaphore.acquire()

        future: Future = executor.submit(fn, *args)
        task_id = id(future)
        self._running_tasks[task_id] = time.monotonic()
        self._total_submitted += 1

        loop = asyncio.get_running_loop()

        def _release() -> None:
            try:
                semaphore.release()
            except (RuntimeError, ValueError):
                pass

        def _on_thread_done(f: Future) -> None:
            self._running_tasks.pop(task_id, None)
            self._total_completed += 1
            loop.call_soon_threadsafe(_release)
            try:
                f.result()
            except Exception:
                pass

        future.add_done_callback(_on_thread_done)

        af = asyncio.wrap_future(future)
        try:
            return await asyncio.wait_for(
                asyncio.shield(af), timeout=effective_timeout,
            )
        except asyncio.TimeoutError:
            self._total_timed_out += 1
            running_count = len(self._running_tasks)
            logger.error(
                "OCR task timed out after %ds. "
                "The thread continues in background (Python threads cannot "
                "be forcibly terminated). Semaphore remains held until it "
                "finishes. Currently tracking %d running tasks.",
                effective_timeout, running_count,
            )
            raise OcrTaskTimeoutError(
                f"OCR task timed out after {effective_timeout}s"
            )

    # --- lifecycle ---------------------------------------------------------

    async def shutdown(self, wait: bool = True) -> None:
        self._shutdown = True
        if self._executor is not None:
            self._executor.shutdown(wait=wait, cancel_futures=True)
            logger.info(
                "OCR executor shut down. "
                "total_submitted=%d total_completed=%d timed_out=%d queue_full=%d",
                self._total_submitted, self._total_completed,
                self._total_timed_out, self._total_queue_full,
            )

    @property
    def stats(self) -> dict:
        return {
            "submitted": self._total_submitted,
            "completed": self._total_completed,
            "timed_out": self._total_timed_out,
            "queue_full": self._total_queue_full,
            "pending": self._total_submitted - self._total_completed,
            "running": len(self._running_tasks),
            "max_workers": self._max_workers,
            "max_concurrency": self._max_concurrency,
            "max_queue_size": self._max_queue_size,
            "task_timeout": self._task_timeout,
            "shutdown": self._shutdown,
        }


# Process-wide singleton
ocr_executor = _OcrExecutorService()
