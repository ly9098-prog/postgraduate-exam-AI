"""OcrWorkerPool — 父进程管理 N 个 worker 的有界队列池。

设计约束：
- 父进程持有 ``asyncio.Queue``（有界 pending queue）
- 每个 worker 同一时间只持有一个 active task
- 超时只 terminate/kill 被分配的 worker，不丢失父队列中的其他任务
- worker 被杀后 pipe 必须重建（不重用可能损坏的 Connection）
- 旧 generation 的迟到结果通过 ``request_id`` 匹配丢弃
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import deque
from typing import Any, Callable

from app.core.ocr_types import (
    STABLE_ERROR_CODES,
    WorkerPoolMetrics,
    WorkerRequest,
    WorkerResult,
    _PROTOCOL_VERSION,
)
from app.core.ocr_worker_process import OcrWorkerProcess

logger = logging.getLogger(__name__)


class OcrWorkerPool:
    """有界、可恢复的 OCR worker 进程池。

    Usage::

        pool = OcrWorkerPool(config)
        result = await pool.submit(image_bytes, page_index=0, mode="boxes")
        metrics = pool.metrics
        await pool.shutdown()
    """

    def __init__(self, config: Any) -> None:
        self._config = config
        self._stopped = False

        # Pending queue (bounded)
        self._pending: asyncio.Queue[WorkerRequest] = asyncio.Queue(
            maxsize=config.queue_capacity,
        )

        # Workers
        self._workers: list[OcrWorkerProcess | None] = [
            None for _ in range(config.worker_count)
        ]
        # Per-worker asyncio.Event: set when worker is idle
        self._worker_events: list[asyncio.Event] = [
            asyncio.Event() for _ in range(config.worker_count)
        ]
        for event in self._worker_events:
            event.set()  # All workers start idle

        # Active tasks: request_id → (asyncio.Future[WorkerResult], worker_id, worker_generation)
        self._active_tasks: dict[
            str, tuple[asyncio.Future, int, int]
        ] = {}

        # Consumer tasks (one per worker slot)
        self._consumers: list[asyncio.Task] = []
        self._generation: int = 0

        # Metrics
        self._metrics = WorkerPoolMetrics()

        # Restart tracking
        self._restart_times: deque[float] = deque(
            maxlen=config.max_restarts_per_window,
        )

        # Start consumers
        loop = asyncio.get_event_loop()
        for wid in range(config.worker_count):
            task = loop.create_task(
                self._consumer_loop(wid),
                name=f"ocr-worker-consumer-{wid}",
            )
            self._consumers.append(task)

    # ── Public API ──────────────────────────────────────────────────────────

    async def submit(
        self,
        image_bytes: bytes,
        page_index: int = 0,
        *,
        mode: str = "boxes",
        options: dict | None = None,
    ) -> WorkerResult:
        """Submit an OCR task and wait for result.

        Raises:
            asyncio.TimeoutError: Task waited too long in queue or execution.
        """
        if self._stopped:
            return WorkerResult(
                request_id="",
                status="failed",
                stable_error_code=STABLE_ERROR_CODES["SHUTDOWN"],
                error_type="Pool is shut down",
            )

        req = self._build_request(image_bytes, page_index, mode, options)

        # Try to add to pending queue (fast-fail if full)
        try:
            await asyncio.wait_for(
                self._pending.put(req),
                timeout=1.0,  # short wait for queue space
            )
            self._metrics.accepted += 1
        except asyncio.TimeoutError:
            self._metrics.queue_full += 1
            return WorkerResult(
                request_id=req.request_id,
                page_index=page_index,
                status="failed",
                stable_error_code=STABLE_ERROR_CODES["QUEUE_FULL"],
                error_type=f"Queue full (capacity={self._config.queue_capacity})",
            )

        # Wait for result
        future: asyncio.Future[WorkerResult] = asyncio.get_event_loop().create_future()
        self._active_tasks[req.request_id] = (future, -1, req.worker_generation)
        self._metrics.queued += 1

        try:
            result = await asyncio.wait_for(
                future,
                timeout=self._config.total_deadline,
            )
            return result
        except asyncio.TimeoutError:
            self._metrics.queue_wait_timeout += 1
            self._active_tasks.pop(req.request_id, None)
            self._metrics.queued -= 1
            return WorkerResult(
                request_id=req.request_id,
                page_index=page_index,
                status="failed",
                stable_error_code=STABLE_ERROR_CODES["QUEUE_TIMEOUT"],
                error_type=f"Total deadline ({self._config.total_deadline}s) exceeded",
            )
        except Exception as exc:
            self._active_tasks.pop(req.request_id, None)
            self._metrics.queued -= 1
            return WorkerResult(
                request_id=req.request_id,
                page_index=page_index,
                status="failed",
                stable_error_code=STABLE_ERROR_CODES["ENGINE_ERROR"],
                error_type=str(exc),
            )

    async def shutdown(
        self,
        graceful_timeout: float | None = None,
        kill_timeout: float | None = None,
    ) -> None:
        """Stop accepting → drain queue → cancel active → kill workers."""
        self._stopped = True

        gt = graceful_timeout or self._config.shutdown_grace_timeout
        kt = kill_timeout or self._config.kill_timeout

        logger.info("OcrWorkerPool shutting down (graceful=%.0fs kill=%.0fs)", gt, kt)

        # Cancel consumers
        for task in self._consumers:
            task.cancel()
        await asyncio.gather(*self._consumers, return_exceptions=True)

        # Fail all pending tasks
        while not self._pending.empty():
            try:
                req = self._pending.get_nowait()
                self._fail_future(
                    req.request_id,
                    STABLE_ERROR_CODES["SHUTDOWN"],
                    "Pool shutting down",
                )
            except asyncio.QueueEmpty:
                break

        # Fail active tasks
        for rid in list(self._active_tasks.keys()):
            self._fail_future(
                rid,
                STABLE_ERROR_CODES["SHUTDOWN"],
                "Pool shutting down",
            )

        # Kill workers
        for wid, worker in enumerate(self._workers):
            if worker is not None:
                try:
                    worker.ensure_dead(kill_timeout=kt)
                except Exception as exc:
                    logger.warning("Worker[%d] shutdown error: %s", wid, exc)
                worker.close_pipe()

        # Log final metrics
        logger.info(
            "OcrWorkerPool shut down. metrics=%s", self._metrics.snapshot(),
        )

    @property
    def metrics(self) -> dict:
        """Return worker pool lifecycle metrics."""
        m = self._metrics.snapshot()
        m["capacity"] = self._config.worker_count
        m["capacity_available"] = self._config.worker_count - m["running"]
        m["generation"] = self._generation
        m["stopped"] = self._stopped
        m["alive_workers"] = sum(
            1 for w in self._workers if w is not None and w.is_alive()
        )
        return m

    # ── Internal: Consumer ──────────────────────────────────────────────────

    async def _consumer_loop(self, worker_id: int) -> None:
        """Consumer task for a single worker slot."""
        while not self._stopped:
            try:
                # Wait for a task from pending queue (with timeout for poll)
                req = await asyncio.wait_for(
                    self._pending.get(),
                    timeout=1.0,
                )
            except asyncio.TimeoutError:
                continue  # Re-check _stopped flag

            self._metrics.queued -= 1

            # Ensure worker exists
            worker = await self._ensure_worker(worker_id)
            if worker is None:
                # Worker could not be started
                self._fail_future(
                    req.request_id,
                    STABLE_ERROR_CODES["WORKER_STARTUP_FAILED"],
                    "Worker could not be started",
                )
                continue

            # Update active task tracking
            entry = self._active_tasks.get(req.request_id)
            if entry is None:
                # Task was already cancelled/timeout
                self._metrics.stale_discarded += 1
                continue

            self._active_tasks[req.request_id] = (entry[0], worker_id, worker.generation)
            self._metrics.running += 1

            # Send request to worker
            try:
                worker.send_request(req)
            except RuntimeError as exc:
                logger.warning("Worker[%d] send failed: %s", worker_id, exc)
                self._handle_worker_failure(worker_id, req.request_id, str(exc))
                continue

            # Wait for result with timeout
            loop = asyncio.get_event_loop()
            try:
                result = await asyncio.wait_for(
                    loop.run_in_executor(
                        None, worker.receive_result_blocking,
                    ),
                    timeout=self._config.execution_timeout,
                )

                # Check for stale result (generation mismatch)
                if result.request_id not in self._active_tasks:
                    self._metrics.stale_discarded += 1
                    self._metrics.late_finished += 1
                    continue

                if result.worker_generation != worker.generation:
                    self._metrics.stale_discarded += 1
                    continue

                # Complete future
                if result.status == "success":
                    self._metrics.finished += 1
                else:
                    self._metrics.failed += 1
                self._set_future_result(result.request_id, result)

            except asyncio.TimeoutError:
                self._metrics.timed_out += 1
                logger.warning(
                    "Worker[%d] execution timeout (%ds), killing",
                    worker_id, self._config.execution_timeout,
                )
                self._kill_and_replace_worker(worker_id)
                self._fail_future(
                    req.request_id,
                    STABLE_ERROR_CODES["EXECUTION_TIMEOUT"],
                    f"Execution timeout ({self._config.execution_timeout}s)",
                )
            except Exception as exc:
                logger.warning("Worker[%d] unexpected error: %s", worker_id, exc)
                self._handle_worker_failure(worker_id, req.request_id, str(exc))

            self._metrics.running -= 1

    # ── Internal: Worker management ─────────────────────────────────────────

    async def _ensure_worker(self, worker_id: int) -> OcrWorkerProcess | None:
        """Ensure worker slot has a live worker. Start one if missing."""
        worker = self._workers[worker_id]
        if worker is not None and worker.is_alive():
            return worker

        # Check restart rate limit
        if not self._allow_restart():
            logger.error(
                "Worker[%d] restart rate limit exceeded, "
                "not starting replacement",
                worker_id,
            )
            # Close old worker if still around
            if worker is not None:
                worker.close_pipe()
                worker = None
            self._workers[worker_id] = None
            return None

        self._generation += 1
        start_time = time.monotonic()

        try:
            new_worker = OcrWorkerProcess(
                worker_id=worker_id,
                generation=self._generation,
                config=self._config,
            )
            new_worker.start()
            self._metrics.restarted += 1

            # Record restart time for rate limiting
            self._restart_times.append(time.monotonic())

            # Close old worker
            if worker is not None:
                worker.close_pipe()

            self._workers[worker_id] = new_worker

            elapsed = time.monotonic() - start_time
            logger.info(
                "Worker[%d] replaced g%d→g%d (pid=%d) in %.1fs",
                worker_id, worker.generation if worker else -1,
                self._generation, new_worker.pid, elapsed,
            )
            return new_worker

        except Exception as exc:
            self._metrics.crashed += 1
            logger.error("Worker[%d] start failed: %s", worker_id, exc)
            self._workers[worker_id] = None
            return None

    def _allow_restart(self) -> bool:
        """Check if restart is allowed within rate limit."""
        now = time.monotonic()
        window = self._config.restart_window_seconds

        # Remove entries outside window
        while self._restart_times and (
            now - self._restart_times[0] > window
        ):
            self._restart_times.popleft()

        return len(self._restart_times) < self._config.max_restarts_per_window

    def _kill_and_replace_worker(self, worker_id: int) -> None:
        """Kill a worker and record crash."""
        worker = self._workers[worker_id]
        if worker is not None:
            try:
                worker.ensure_dead(kill_timeout=self._config.kill_timeout)
            except Exception as exc:
                logger.warning("Worker[%d] ensure_dead error: %s", worker_id, exc)
            worker.close_pipe()
            self._metrics.crashed += 1
        self._workers[worker_id] = None

    def _handle_worker_failure(
        self, worker_id: int, request_id: str, error: str,
    ) -> None:
        """Handle worker failure and fail the active task."""
        self._kill_and_replace_worker(worker_id)
        self._fail_future(
            request_id,
            STABLE_ERROR_CODES["WORKER_CRASH"],
            error,
        )

    # ── Internal: Future management ─────────────────────────────────────────

    def _set_future_result(self, request_id: str, result: WorkerResult) -> None:
        entry = self._active_tasks.pop(request_id, None)
        if entry is None:
            return
        future = entry[0]
        if not future.done():
            future.set_result(result)

    def _fail_future(
        self, request_id: str, code: str, message: str,
    ) -> None:
        entry = self._active_tasks.pop(request_id, None)
        if entry is None:
            return
        future = entry[0]
        if not future.done():
            result = WorkerResult(
                request_id=request_id,
                status="failed",
                stable_error_code=code,
                error_type=message,
            )
            future.set_result(result)

    def _build_request(
        self,
        image_bytes: bytes,
        page_index: int,
        mode: str,
        options: dict | None,
    ) -> WorkerRequest:
        import hashlib

        request_id = uuid.uuid4().hex
        now = time.monotonic()
        image_hash = hashlib.sha256(image_bytes).hexdigest()[:16]

        return WorkerRequest(
            request_id=request_id,
            page_index=page_index,
            mode=mode,
            worker_generation=self._generation,
            submitted_monotonic=now,
            deadline_monotonic=now + self._config.total_deadline,
            image_hash=image_hash,
            image_bytes=image_bytes,
            options=options or {},
        )
