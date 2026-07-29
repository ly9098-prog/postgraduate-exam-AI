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
import threading
import time
from concurrent.futures import Future, ProcessPoolExecutor, TimeoutError
from concurrent.futures.process import BrokenProcessPool
from typing import Any

logger = logging.getLogger(__name__)

# Default timeout for process-pool OCR (seconds).
# Longer than the thread-pool timeout since process startup + model load
# adds overhead on recovery.
_PROCESS_TIMEOUT = 120

# One OCR engine per child process.  ProcessPoolExecutor's initializer creates
# it eagerly; the lazy getter is a defensive fallback for direct helper calls
# (for example in tests).  Re-creating PaddleOCR per page reloads model state,
# repeats health checks and causes severe CPU/GPU memory churn.
_WORKER_ENGINE: Any | None = None


def _get_worker_engine() -> Any:
    global _WORKER_ENGINE
    if _WORKER_ENGINE is None:
        from app.core.ocr_engine import create_engine_for_child
        _WORKER_ENGINE = create_engine_for_child()
    return _WORKER_ENGINE


def _init_worker() -> None:
    """Initialize PaddleOCR once per worker process.

    Called by ``ProcessPoolExecutor`` when spawning a new worker.
    Suppresses Paddle inference logging in the child process.
    """
    os.environ["GLOG_minloglevel"] = "2"
    try:
        _get_worker_engine()
        logger.info("Process worker PaddleOCR initialized (pid=%d)", os.getpid())
    except Exception as exc:
        logger.error("Process worker PaddleOCR init failed (pid=%d): %s",
                      os.getpid(), exc)
        raise


def _run_one_page(image_bytes: bytes, page_index: int) -> str:
    """Run OCR on a single page in the worker process (text only).

    This MUST be a module-level function (pickled across process boundary).
    """
    engine = _get_worker_engine()
    result = engine.recognize(image_bytes, page_index, mode="text")
    return result.get("text", "")


def _run_one_page_with_boxes(
    image_bytes: bytes, page_index: int, skip_rotation: bool = False,
) -> dict:
    """Run OCR on a single page and return text + detection boxes.

    Returns a dict with keys:
      page_index, text, boxes (list[dict]), failed, error

    Module-level for pickling across process boundary.
    """
    engine = _get_worker_engine()
    result = engine.recognize(image_bytes, page_index, skip_rotation=skip_rotation, mode="boxes")
    return {
        "page_index": result.get("page_index", page_index),
        "text": result.get("text", ""),
        "boxes": result.get("boxes", []),
        "failed": result.get("failed", False),
        "error": result.get("error"),
    }


def _run_lightweight_ocr(image_bytes: bytes, page_index: int) -> dict:
    """Lightweight OCR for exercise region detection.

    Minimal preprocessing (autocontrast + resize, no deskew/crop).
    cls=False for speed.
    Runs in child ProcessPoolExecutor worker.
    """
    import io

    import numpy as np
    from PIL import Image, ImageOps

    engine = _get_worker_engine()
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    img = ImageOps.autocontrast(img.convert("L"), cutoff=1).convert("RGB")
    img = engine._resize(img)

    arr = np.array(img)
    with engine._lock:
        raw_result = engine._ocr.ocr(arr, cls=False)

    text_parts: list[str] = []
    for line_group in raw_result or []:
        if line_group is None:
            continue
        for line_info in line_group:
            if line_info and len(line_info) >= 2 and line_info[1]:
                text_parts.append(str(line_info[1][0]))

    return {"page_index": page_index, "text": "\n".join(text_parts)}


class OcrProcessPool:
    """Process-isolated pool for running PaddleOCR inference.

    Maintains a single-worker ``ProcessPoolExecutor``. On crash
    (``BrokenProcessPool``) or after timeout the process pool is
    non-blockingly shut down (cancelling pending futures) and a
    fresh one is created automatically on the next submission.

    After ``shutdown()`` (graceful, permanent) the pool refuses
    new submissions. Call ``reset()`` to re-enable if the
    application continues running.
    """

    def __init__(self, max_workers: int = 1):
        self._max_workers = max_workers
        self._executor: ProcessPoolExecutor | None = None
        self._spawn_count: int = 0
        self._total_submitted: int = 0
        self._total_timeouts: int = 0
        self._total_crashes: int = 0
        self._shut_down: bool = False
        self._lock = threading.RLock()

    def _ensure(self) -> ProcessPoolExecutor:
        with self._lock:
            if self._shut_down:
                raise RuntimeError("OCR process pool has been shut down")
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
        executor = self._ensure()
        try:
            future = executor.submit(_run_one_page, image_bytes, page_index)
        except BrokenProcessPool:
            self._total_crashes += 1
            logger.warning(
                "OCR process pool broken, recreating (crash=%d)",
                self._total_crashes,
            )
            self._shutdown_nonblocking(expected=executor)
            executor = self._ensure()
            future = executor.submit(_run_one_page, image_bytes, page_index)
        except RuntimeError:
            # From _ensure() during shutdown — do not retry, do not count as crash
            raise

        setattr(future, "_ocr_pool_executor", executor)
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
            self._shutdown_nonblocking(
                expected=getattr(future, "_ocr_pool_executor", None),
            )
            raise
        except Exception:
            self._shutdown_nonblocking(
                expected=getattr(future, "_ocr_pool_executor", None),
            )
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
        executor = self._ensure()
        try:
            future = executor.submit(
                _run_one_page_with_boxes, image_bytes, page_index, skip_rotation,
            )
        except BrokenProcessPool:
            self._total_crashes += 1
            self._shutdown_nonblocking(expected=executor)
            executor = self._ensure()
            future = executor.submit(
                _run_one_page_with_boxes, image_bytes, page_index, skip_rotation,
            )
        except RuntimeError:
            raise

        self._total_submitted += 1
        try:
            return future.result(timeout=effective_timeout)
        except TimeoutError:
            self._total_timeouts += 1
            self._shutdown_nonblocking(expected=executor)
            raise
        except Exception:
            self._shutdown_nonblocking(expected=executor)
            raise

    def get_lightweight_text(
        self,
        image_bytes: bytes,
        page_index: int = 0,
        timeout: int | None = None,
    ) -> str:
        """Lightweight OCR for exercise region detection.

        Minimal preprocessing (autocontrast + resize, no deskew).
        cls=False for speed. Runs in child process.
        """
        effective_timeout = timeout or _PROCESS_TIMEOUT
        executor = self._ensure()
        try:
            future = executor.submit(
                _run_lightweight_ocr, image_bytes, page_index,
            )
        except BrokenProcessPool:
            self._total_crashes += 1
            self._shutdown_nonblocking(expected=executor)
            executor = self._ensure()
            future = executor.submit(
                _run_lightweight_ocr, image_bytes, page_index,
            )
        except RuntimeError:
            raise

        self._total_submitted += 1
        try:
            result = future.result(timeout=effective_timeout)
            return result.get("text", "")
        except TimeoutError:
            self._total_timeouts += 1
            self._shutdown_nonblocking(expected=executor)
            raise
        except Exception:
            self._shutdown_nonblocking(expected=executor)
            raise

    def _detach_executor(
        self,
        expected: ProcessPoolExecutor | None = None,
    ) -> ProcessPoolExecutor | None:
        with self._lock:
            if expected is not None and self._executor is not expected:
                return None
            executor = self._executor
            self._executor = None
            return executor

    @staticmethod
    def _stop_executor(
        executor: ProcessPoolExecutor,
        *,
        grace_timeout: float,
    ) -> None:
        """Stop an executor and guarantee its worker processes do not leak.

        ``ProcessPoolExecutor.shutdown(wait=False)`` does not terminate a native
        OCR call that is already running.  Snapshot the private process handles
        before shutdown, allow a bounded grace period, then terminate/kill any
        survivors.  This is intentionally isolated here because the public
        executor API has no force-stop primitive.
        """
        processes = list(
            (getattr(executor, "_processes", None) or {}).values()
        )
        try:
            executor.shutdown(wait=False, cancel_futures=True)
        except Exception as exc:
            logger.warning("OCR process pool shutdown signal error: %s", exc)

        deadline = time.monotonic() + max(0.0, grace_timeout)
        for process in processes:
            remaining = max(0.0, deadline - time.monotonic())
            if remaining > 0:
                try:
                    process.join(remaining)
                except Exception:
                    pass

        survivors = [p for p in processes if p.is_alive()]
        for process in survivors:
            try:
                process.terminate()
            except Exception:
                pass
        for process in survivors:
            try:
                process.join(1.0)
            except Exception:
                pass
        for process in survivors:
            if process.is_alive():
                try:
                    process.kill()
                except (AttributeError, OSError):
                    try:
                        process.terminate()
                    except Exception:
                        pass
                try:
                    process.join(1.0)
                except Exception:
                    pass
        for process in processes:
            try:
                process.close()
            except (AttributeError, ValueError, OSError):
                pass

    def _shutdown_nonblocking(
        self,
        *,
        expected: ProcessPoolExecutor | None = None,
    ) -> None:
        """Immediately recycle the current executor and kill running OCR."""
        executor = self._detach_executor(expected)
        if executor is not None:
            self._stop_executor(executor, grace_timeout=0.0)

    def shutdown(self, wait: bool = True) -> None:
        """Permanently stop the pool with a bounded shutdown.

        ``wait=True`` allows up to five seconds for a running page to finish,
        then force-stops the child.  This avoids an application shutdown hanging
        forever in native OCR code.
        """
        with self._lock:
            self._shut_down = True
        executor = self._detach_executor()
        if executor is not None:
            self._stop_executor(executor, grace_timeout=5.0 if wait else 0.0)

    def reset(self) -> None:
        """Re-enable the pool after shutdown.

        Allows new submissions to create a fresh executor.
        """
        with self._lock:
            self._shut_down = False
            self._executor = None

    @property
    def stats(self) -> dict:
        with self._lock:
            return {
                "spawn_count": self._spawn_count,
                "total_submitted": self._total_submitted,
                "total_timeouts": self._total_timeouts,
                "total_crashes": self._total_crashes,
                "alive": self._executor is not None,
            }


# Process-wide singleton
ocr_process_pool = OcrProcessPool(max_workers=1)
