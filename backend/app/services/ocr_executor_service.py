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

    Design:
    - Uses a dedicated ``ThreadPoolExecutor`` (never the default one).
    - ``asyncio.Semaphore`` caps in-flight async tasks queuing to the pool.
    - An internal counter tracks how many tasks are *submitted but not yet
      completed* (including those queued inside the thread pool). When this
      exceeds ``_max_queue_size``, new submissions raise ``OcrQueueFullError``.
    - On timeout: the ``Future`` is not cancelled (Python threads cannot be
      forcibly terminated), but the caller receives ``OcrTaskTimeoutError``
      immediately and the thread is left to finish in the background. The
      thread pool's worker count caps cumulative thread growth.
    - On shutdown: ``_executor.shutdown(wait=True)`` waits for running tasks
      to finish (respects ``cancel_futures=True`` for queued ones).
    """

    def __init__(self) -> None:
        self._executor: ThreadPoolExecutor | None = None
        self._semaphore: asyncio.Semaphore | None = None
        self._lock = threading.Lock()
        self._shutdown = False

        # Configuration — read from settings once, but allow override
        self._max_workers: int = settings.OCR_EXECUTOR_WORKERS
        self._max_concurrency: int = settings.OCR_MAX_CONCURRENCY
        self._max_queue_size: int = settings.OCR_MAX_QUEUE_SIZE
        self._task_timeout: int = settings.OCR_TASK_TIMEOUT_SEC

        # Running task tracking for diagnostics
        self._running_tasks: dict[int, float] = {}  # id(task) -> submit_time
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
        """Return the shared thread pool for sync OCR callers.

        Sync callers (ocr_pages, ocr_pages_with_boxes) use this instead of
        creating their own ThreadPoolExecutor, ensuring total worker count
        stays bounded by ``OCR_EXECUTOR_WORKERS``.
        """
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=self._max_workers,
                thread_name_prefix="ocr_exec",
            )
        return self._executor

    # --- public API --------------------------------------------------------

    async def run_ocr(
        self,
        image_bytes: bytes,
        timeout: int | None = None,
    ) -> str:
        """Run ``ocr_image`` in a thread and return the recognised text.

        Raises:
            OcrQueueFullError: queue capacity exceeded.
            OcrTaskTimeoutError: task exceeded its timeout.
            RuntimeError: OCR is disabled or the image is empty.
        """
        from app.services.ocr_service import ocr_image

        return await self._run_in_executor(ocr_image, image_bytes, timeout=timeout)

    async def run_ocr_one_page(
        self,
        image_bytes: bytes,
        page_index: int = 0,
        timeout: int | None = None,
    ) -> str:
        """Run ``_ocr_one_page`` in a thread and return (page_index, text)."""
        from app.services.ocr_service import _ocr_one_page

        _, text = await self._run_in_executor(
            _ocr_one_page, image_bytes, page_index,
            timeout=timeout,
        )
        return text

    async def run_ocr_pages(
        self,
        page_images: list[tuple[int, bytes]],
        timeout: int | None = None,
    ) -> dict[int, str]:
        """Concurrently OCR multiple pages through the bounded executor.

        Each page is submitted as an individual task through the semaphore,
        so overall concurrency stays within ``_max_concurrency``.
        """
        if not page_images:
            return {}

        from app.services.ocr_service import _ocr_one_page

        results: dict[int, str] = {}

        async def _ocr_one(png: bytes, idx: int) -> tuple[int, str | None]:
            try:
                _, text = await self._run_in_executor(
                    _ocr_one_page, png, idx,
                    timeout=timeout,
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

    async def run_ocr_pages_in_process(
        self,
        page_images: list[tuple[int, bytes]],
        timeout: int | None = None,
    ) -> dict[int, str]:
        """OCR multiple pages with true process isolation and timeout.

        Uses ``OcrProcessPool`` instead of thread pool so that:
        - A C++ crash (SIGSEGV) kills only the worker, not the API process.
        - Timeout enforcement via process termination (not just "give up").
        - GPU memory is isolated.

        Falls back to thread pool when the process pool is unavailable
        (e.g. PaddleOCR not installed).
        """
        if not page_images:
            return {}

        effective_timeout = timeout if timeout is not None else self._task_timeout
        results: dict[int, str] = {}

        try:
            from app.core.ocr_process_pool import ocr_process_pool

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
        except ImportError:
            logger.warning(
                "OCR process pool unavailable, falling back to thread pool"
            )
            return await self.run_ocr_pages(page_images, timeout=timeout)

        return results

    async def run_ocr_pages_with_boxes_in_process(
        self,
        page_images: list[tuple[int, bytes]],
        skip_rotation: bool = False,
        timeout: int | None = None,
    ) -> dict[int, dict]:
        """OCR multiple pages with process isolation, returning text + boxes.

        Each page runs sequentially in the process pool (max_workers=1).
        Returns {page_index: {page_index, text, boxes, failed, error}}.

        Falls back to thread pool when process pool unavailable.
        """
        if not page_images:
            return {}

        effective_timeout = timeout if timeout is not None else self._task_timeout

        try:
            from app.core.ocr_process_pool import ocr_process_pool

            results: dict[int, dict] = {}
            for idx, png in page_images:
                try:
                    result = await asyncio.wait_for(
                        asyncio.get_event_loop().run_in_executor(
                            None,
                            ocr_process_pool.get_text_with_boxes,
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
            logger.warning(
                "OCR process pool unavailable, falling back to thread pool"
            )
            return await self.run_ocr_pages_with_boxes(
                page_images, skip_rotation=skip_rotation, timeout=timeout,
            )

    async def run_ocr_pages_with_boxes(
        self,
        page_images: list[tuple[int, bytes]],
        skip_rotation: bool = False,
        timeout: int | None = None,
    ) -> dict[int, Any]:
        """OCR pages and return results with detection boxes."""
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

    # --- internal ----------------------------------------------------------

    async def _run_in_executor(
        self,
        fn: callable,
        *args: Any,
        timeout: int | None = None,
    ) -> Any:
        """Submit *fn(*args)* to the thread pool with semaphore and timeout.

        Semaphore capacity is held until the underlying thread actually finishes
        (not until the caller times out). This prevents excessive concurrent
        inference even when callers have given up waiting.

        Uses ``asyncio.wrap_future`` instead of
        ``loop.run_in_executor(None, future.result)`` so no default thread pool
        thread is consumed just to wait.
        """
        if self._shutdown:
            raise RuntimeError("OCR executor is shut down")

        effective_timeout = timeout if timeout is not None else self._task_timeout

        # Fast-fail if queue is too deep
        pending = self._total_submitted - self._total_completed
        if pending >= self._max_queue_size:
            self._total_queue_full += 1
            raise OcrQueueFullError(
                f"OCR queue full ({pending} pending, max {self._max_queue_size})"
            )

        executor, semaphore = self._ensure_executor()

        # Acquire before submitting; released in done_callback so capacity
        # stays aligned with the real thread lifetime.
        await semaphore.acquire()

        future: Future = executor.submit(fn, *args)
        task_id = id(future)
        self._running_tasks[task_id] = time.monotonic()
        self._total_submitted += 1

        # done_callback releases capacity and counts completion when the
        # underlying thread *actually* finishes — not when the caller stops
        # waiting. This prevents the pending counter from growing forever
        # after repeated timeouts.
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
                f.result()  # consume exception so it's not logged unhandled
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
        """Shut down the executor.

        If *wait* is True, blocks until all running tasks finish.
        Queued (not yet started) futures are cancelled.
        """
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
