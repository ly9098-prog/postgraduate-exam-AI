"""Process-isolated OCR inference pool.

Runs PaddleOCR inference in a separate process via
``concurrent.futures.ProcessPoolExecutor`` so that:

- A C++ crash (SIGSEGV) in Paddle/BLAS/CUDA kills only the worker,
  not the API process.
- True timeout enforcement via process termination.
- GPU memory is isolated per worker.

When a worker crashes or times out, the process pool is automatically
recycled (old process terminated, new one spawned with a fresh PaddleOCR
instance).

Usage::

    from app.core.ocr_process_pool import ocr_process_pool

    future = ocr_process_pool.submit(image_bytes, page_index=0)
    text = future.result(timeout=60)
"""

from __future__ import annotations

import logging
import os
import time
from concurrent.futures import Future, ProcessPoolExecutor, TimeoutError
from concurrent.futures.process import BrokenProcessPool

logger = logging.getLogger(__name__)

# Default timeout for process-pool OCR (seconds).
# Longer than the thread-pool timeout since process startup + model load
# adds overhead on recovery.
_PROCESS_TIMEOUT = 120


def _init_worker() -> None:
    """Initialize PaddleOCR once per worker process.

    Called by ``ProcessPoolExecutor`` when spawning a new worker.
    Suppresses Paddle inference logging in the child process.
    """
    os.environ["GLOG_minloglevel"] = "2"
    try:
        from app.services.ocr_service import _get_ocr
        _get_ocr()
        logger.info("Process worker PaddleOCR initialized (pid=%d)", os.getpid())
    except Exception as exc:
        logger.error("Process worker PaddleOCR init failed (pid=%d): %s",
                      os.getpid(), exc)
        raise


def _run_one_page(image_bytes: bytes, page_index: int) -> str:
    """Run OCR on a single page in the worker process (text only).

    This MUST be a module-level function (pickled across process boundary).
    """
    from app.services.ocr_service import _ocr_one_page
    _, text = _ocr_one_page(image_bytes, page_index)
    return text


def _run_one_page_with_boxes(
    image_bytes: bytes, page_index: int, skip_rotation: bool = False,
) -> dict:
    """Run OCR on a single page and return text + detection boxes.

    Returns a dict with keys:
      page_index, text, boxes (list[dict]), failed, error

    Module-level for pickling across process boundary.
    """
    from app.services.ocr_service import _ocr_one_page_with_boxes
    result = _ocr_one_page_with_boxes(image_bytes, page_index, skip_rotation)
    return {
        "page_index": result.page_index,
        "text": result.text,
        "boxes": result.boxes or [],
        "failed": result.failed,
        "error": result.error,
    }


class OcrProcessPool:
    """Process-isolated pool for running PaddleOCR inference.

    Maintains a single-worker ``ProcessPoolExecutor``. On crash
    (``BrokenProcessPool``) or after timeout the executor is shut down
    and a fresh one is created automatically.
    """

    def __init__(self, max_workers: int = 1):
        self._max_workers = max_workers
        self._executor: ProcessPoolExecutor | None = None
        self._spawn_count: int = 0
        self._total_submitted: int = 0
        self._total_timeouts: int = 0
        self._total_crashes: int = 0

    def _ensure(self) -> ProcessPoolExecutor:
        if self._executor is None:
            self._executor = ProcessPoolExecutor(
                max_workers=self._max_workers,
                initializer=_init_worker,
            )
            self._spawn_count += 1
            logger.info(
                "OCR process pool spawned (pid=%d, spawn=%d)",
                os.getpid(), self._spawn_count,
            )
        return self._executor

    def submit(
        self,
        image_bytes: bytes,
        page_index: int = 0,
    ) -> Future:
        """Submit a single-page OCR task to the process pool.

        If the pool has crashed since the last submission, it is
        automatically recreated.

        Returns:
            A ``Future`` whose ``.result()`` returns the OCR text.
        """
        try:
            future = self._ensure().submit(_run_one_page, image_bytes, page_index)
        except (BrokenProcessPool, RuntimeError):
            self._total_crashes += 1
            logger.warning(
                "OCR process pool broken, recreating (crash=%d)",
                self._total_crashes,
            )
            self._shutdown_now()
            future = self._ensure().submit(_run_one_page, image_bytes, page_index)

        self._total_submitted += 1
        return future

    def get_text(
        self,
        image_bytes: bytes,
        page_index: int = 0,
        timeout: int | None = None,
    ) -> str:
        """Convenience: submit + wait for result with timeout.

        On timeout the process pool is recycled (worker terminated) so
        that a hanging PaddleOCR call never blocks indefinitely.

        Raises:
            TimeoutError: OCR exceeded the timeout.
            RuntimeError: OCR failed or process crashed.
        """
        effective_timeout = timeout or _PROCESS_TIMEOUT
        future = self.submit(image_bytes, page_index)
        try:
            return future.result(timeout=effective_timeout)
        except TimeoutError:
            self._total_timeouts += 1
            logger.error(
                "OCR process timed out after %ds, recycling pool (timeout=%d)",
                effective_timeout, self._total_timeouts,
            )
            self._shutdown_now()
            raise
        except Exception:
            self._shutdown_now()
            raise

    def get_text_with_boxes(
        self,
        image_bytes: bytes,
        page_index: int = 0,
        skip_rotation: bool = False,
        timeout: int | None = None,
    ) -> dict:
        """Submit a page OCR task and return text + detection boxes.

        Returns:
            dict with keys: page_index, text, boxes, failed, error.

        On timeout the process pool is recycled (worker terminated).
        """
        effective_timeout = timeout or _PROCESS_TIMEOUT
        try:
            future = self._ensure().submit(
                _run_one_page_with_boxes, image_bytes, page_index, skip_rotation,
            )
        except (BrokenProcessPool, RuntimeError):
            self._total_crashes += 1
            self._shutdown_now()
            future = self._ensure().submit(
                _run_one_page_with_boxes, image_bytes, page_index, skip_rotation,
            )

        self._total_submitted += 1
        try:
            return future.result(timeout=effective_timeout)
        except TimeoutError:
            self._total_timeouts += 1
            self._shutdown_now()
            raise
        except Exception:
            self._shutdown_now()
            raise

    def _shutdown_now(self) -> None:
        """Shut down the current executor immediately.

        Terminates the worker process (forced kill).
        """
        if self._executor is not None:
            try:
                self._executor.shutdown(wait=False, cancel_futures=True)
            except Exception as exc:
                logger.warning("OCR process pool shutdown error: %s", exc)
            self._executor = None

    def shutdown(self) -> None:
        """Graceful shutdown (waits for running tasks)."""
        if self._executor is not None:
            try:
                self._executor.shutdown(wait=True)
            except Exception as exc:
                logger.warning("OCR process pool graceful shutdown error: %s", exc)
            self._executor = None

    @property
    def stats(self) -> dict:
        return {
            "spawn_count": self._spawn_count,
            "total_submitted": self._total_submitted,
            "total_timeouts": self._total_timeouts,
            "total_crashes": self._total_crashes,
            "alive": self._executor is not None,
        }


# Process-wide singleton
ocr_process_pool = OcrProcessPool(max_workers=1)
