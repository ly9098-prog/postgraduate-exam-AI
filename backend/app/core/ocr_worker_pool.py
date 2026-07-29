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
from typing import Any

from app.core.ocr_types import (
    STABLE_ERROR_CODES,
    WorkerPoolMetrics,
    WorkerRequest,
    WorkerResult,
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
        self._accepting = True
        self._stopped = False

        # Pending queue (bounded)
        self._pending: asyncio.Queue[WorkerRequest] = asyncio.Queue(
            maxsize=config.queue_capacity,
        )

        # Workers
        self._workers: list[OcrWorkerProcess | None] = [
            None for _ in range(config.worker_count)
        ]
        self._started_once: list[bool] = [False for _ in range(config.worker_count)]
        # Active tasks: request_id → (future, worker_id, page_index).
        # Keep page_index here so infrastructure failures (startup/shutdown/
        # timeout) still return a result associated with the correct page.
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
        if not self._accepting:
            return WorkerResult(
                request_id="",
                page_index=page_index,
                status="failed",
                stable_error_code=STABLE_ERROR_CODES["SHUTDOWN"],
                error_type="Pool is shut down",
            )

        req = self._build_request(image_bytes, page_index, mode, options)
        loop = asyncio.get_running_loop()
        future: asyncio.Future[WorkerResult] = loop.create_future()

        # Register before enqueueing.  The old order allowed a fast consumer to
        # dequeue the request before its Future existed, discard it as stale,
        # and leave the caller blocked until the total deadline.
        self._active_tasks[req.request_id] = (future, -1, page_index)
        self._metrics.queued += 1

        # Try to add to pending queue (bounded wait for backpressure)
        try:
            queue_put_timeout = min(
                self._config.queue_wait_timeout,
                max(0.001, req.deadline_monotonic - time.monotonic()),
            )
            await asyncio.wait_for(
                self._pending.put(req),
                timeout=queue_put_timeout,
            )
            self._metrics.accepted += 1
        except TimeoutError:
            self._discard_pending_request(req.request_id)
            self._metrics.queue_full += 1
            return WorkerResult(
                request_id=req.request_id,
                page_index=page_index,
                status="failed",
                stable_error_code=STABLE_ERROR_CODES["QUEUE_FULL"],
                error_type=f"Queue full (capacity={self._config.queue_capacity})",
            )
        except asyncio.CancelledError:
            self._discard_pending_request(req.request_id)
            raise

        # Wait for result
        try:
            remaining = max(0.0, req.deadline_monotonic - time.monotonic())
            if remaining <= 0:
                raise TimeoutError
            result = await asyncio.wait_for(
                asyncio.shield(future),
                timeout=remaining,
            )
            return result
        except TimeoutError:
            entry = self._active_tasks.pop(req.request_id, None)
            if entry is not None and entry[1] < 0:
                self._metrics.queued = max(0, self._metrics.queued - 1)
                self._metrics.queue_wait_timeout += 1
                code = STABLE_ERROR_CODES["QUEUE_TIMEOUT"]
                error = f"Queue/deadline timeout ({self._config.total_deadline}s)"
            else:
                self._metrics.timed_out += 1
                code = STABLE_ERROR_CODES["EXECUTION_TIMEOUT"]
                error = f"Total deadline ({self._config.total_deadline}s) exceeded"
                if entry is not None:
                    await self._kill_worker(entry[1], count_crash=False)
            if not future.done():
                future.cancel()
            return WorkerResult(
                request_id=req.request_id,
                page_index=page_index,
                status="failed",
                stable_error_code=code,
                error_type=error,
            )
        except asyncio.CancelledError:
            entry = self._active_tasks.pop(req.request_id, None)
            if entry is not None and entry[1] < 0:
                self._metrics.queued = max(0, self._metrics.queued - 1)
            elif entry is not None:
                # Native OCR cannot be cancelled through Future.cancel().
                # Terminate the assigned worker so a disconnected caller does
                # not leave GPU/CPU work running until the execution timeout.
                await self._kill_worker(entry[1], count_crash=False)
            if not future.done():
                future.cancel()
            raise
        except Exception as exc:
            entry = self._active_tasks.pop(req.request_id, None)
            if entry is not None and entry[1] < 0:
                self._metrics.queued = max(0, self._metrics.queued - 1)
            if not future.done():
                future.cancel()
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
        """Stop accepting, drain within grace, then cancel and kill workers."""
        if self._stopped:
            return

        self._accepting = False

        gt = (
            self._config.shutdown_grace_timeout
            if graceful_timeout is None
            else max(0.0, graceful_timeout)
        )
        kt = (
            self._config.kill_timeout
            if kill_timeout is None
            else max(0.0, kill_timeout)
        )

        logger.info("OcrWorkerPool shutting down (graceful=%.0fs kill=%.0fs)", gt, kt)

        # Let queued/running work finish for the configured grace period.
        # asyncio.Queue.join() includes items already taken by consumers until
        # task_done() is called, so this also waits for active OCR calls.
        if gt > 0:
            try:
                await asyncio.wait_for(self._pending.join(), timeout=gt)
            except TimeoutError:
                logger.warning(
                    "OcrWorkerPool graceful shutdown timed out after %.1fs; "
                    "cancelling remaining work",
                    gt,
                )

        self._stopped = True

        # Cancel consumers after the grace period. Cancellation of an active
        # consumer kills its native worker so no receive thread is left blocked.
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
                self._pending.task_done()
            except asyncio.QueueEmpty:
                break

        # Fail active tasks
        for rid in list(self._active_tasks.keys()):
            self._fail_future(
                rid,
                STABLE_ERROR_CODES["SHUTDOWN"],
                "Pool shutting down",
            )

        # Kill all remaining workers concurrently. Sequential termination makes
        # shutdown duration scale as worker_count * kill_timeout.
        async def _stop_worker(wid: int, worker: OcrWorkerProcess) -> None:
            try:
                await asyncio.to_thread(worker.ensure_dead, kt)
            except Exception as exc:
                logger.warning("Worker[%d] shutdown error: %s", wid, exc)
            finally:
                worker.close_pipe()
                worker.close_process_handle()
                self._workers[wid] = None

        await asyncio.gather(*(
            _stop_worker(wid, worker)
            for wid, worker in enumerate(self._workers)
            if worker is not None
        ))

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
        m["accepting"] = self._accepting
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
            except TimeoutError:
                continue  # Re-check _stopped flag

            try:
                entry = self._active_tasks.get(req.request_id)
                if entry is None:
                    # Caller timed out/cancelled while the request was queued.
                    self._metrics.stale_discarded += 1
                    continue

                self._metrics.queued = max(0, self._metrics.queued - 1)

                queue_elapsed = time.monotonic() - req.submitted_monotonic
                remaining_deadline = req.deadline_monotonic - time.monotonic()
                if (
                    queue_elapsed > self._config.queue_wait_timeout
                    or remaining_deadline <= 0
                ):
                    self._metrics.queue_wait_timeout += 1
                    self._fail_future(
                        req.request_id,
                        STABLE_ERROR_CODES["QUEUE_TIMEOUT"],
                        f"Queue wait timeout ({queue_elapsed:.1f}s)",
                    )
                    continue

                # Ensure worker exists.  Model startup/handshake is blocking and
                # can take tens of seconds, so it must never run on the loop.
                worker = await self._ensure_worker(worker_id)
                if worker is None:
                    self._fail_future(
                        req.request_id,
                        STABLE_ERROR_CODES["WORKER_STARTUP_FAILED"],
                        "Worker could not be started",
                    )
                    continue

                entry = self._active_tasks.get(req.request_id)
                if entry is None:
                    self._metrics.stale_discarded += 1
                    continue

                # The request is built before a worker generation may exist.
                # Stamp the actual generation immediately before IPC so valid
                # results are not discarded as stale.
                req.worker_generation = worker.generation
                self._active_tasks[req.request_id] = (
                    entry[0], worker_id, req.page_index,
                )
                self._metrics.running += 1

                try:
                    # ``Connection.send`` pickles and writes the full image and
                    # can block on pipe backpressure; offload it as well.
                    await asyncio.to_thread(worker.send_request, req)
                except asyncio.CancelledError:
                    await self._kill_worker(worker_id, count_crash=False)
                    self._metrics.running = max(0, self._metrics.running - 1)
                    raise
                except Exception as exc:
                    logger.warning("Worker[%d] send failed: %s", worker_id, exc)
                    await self._handle_worker_failure(
                        worker_id, req.request_id, str(exc),
                    )
                    self._metrics.running = max(0, self._metrics.running - 1)
                    continue

                execution_budget = min(
                    self._config.execution_timeout,
                    max(0.001, req.deadline_monotonic - time.monotonic()),
                )
                try:
                    result = await asyncio.wait_for(
                        asyncio.to_thread(worker.receive_result_blocking),
                        timeout=execution_budget,
                    )

                    if result.request_id != req.request_id:
                        logger.error(
                            "Worker[%d] protocol desync: expected request %s, got %s",
                            worker_id, req.request_id, result.request_id,
                        )
                        self._metrics.stale_discarded += 1
                        await self._kill_worker(worker_id, count_crash=True)
                        self._fail_future(
                            req.request_id,
                            STABLE_ERROR_CODES["WORKER_CRASH"],
                            "Worker returned a mismatched request_id",
                        )
                        continue

                    if result.request_id not in self._active_tasks:
                        self._metrics.stale_discarded += 1
                        self._metrics.late_finished += 1
                        continue

                    if result.worker_generation != worker.generation:
                        self._metrics.stale_discarded += 1
                        await self._kill_worker(worker_id, count_crash=True)
                        self._fail_future(
                            req.request_id,
                            STABLE_ERROR_CODES["WORKER_CRASH"],
                            "Worker generation mismatch",
                        )
                        continue

                    if result.status == "success":
                        self._metrics.finished += 1
                    else:
                        self._metrics.failed += 1
                    self._set_future_result(result.request_id, result)

                    if self._should_recycle_worker(worker):
                        await self._kill_worker(worker_id, count_crash=False)

                except TimeoutError:
                    self._metrics.timed_out += 1
                    logger.warning(
                        "Worker[%d] execution timeout (%.1fs), killing",
                        worker_id, execution_budget,
                    )
                    await self._kill_worker(worker_id, count_crash=True)
                    self._fail_future(
                        req.request_id,
                        STABLE_ERROR_CODES["EXECUTION_TIMEOUT"],
                        f"Execution timeout ({execution_budget:.1f}s)",
                    )
                except asyncio.CancelledError:
                    # Shutdown/caller cancellation must also unblock the pipe
                    # receiver thread by closing/killing the worker.
                    await self._kill_worker(worker_id, count_crash=False)
                    raise
                except Exception as exc:
                    logger.warning("Worker[%d] unexpected error: %s", worker_id, exc)
                    await self._handle_worker_failure(
                        worker_id, req.request_id, str(exc),
                    )
                finally:
                    self._metrics.running = max(0, self._metrics.running - 1)
            finally:
                self._pending.task_done()

    # ── Internal: Worker management ─────────────────────────────────────────

    async def _ensure_worker(self, worker_id: int) -> OcrWorkerProcess | None:
        """Ensure worker slot has a live worker. Start one if missing."""
        worker = self._workers[worker_id]
        if worker is not None and worker.is_alive():
            return worker

        is_restart = self._started_once[worker_id]

        # Initial startup for each configured slot must not consume the restart
        # budget; otherwise worker_count > max_restarts_per_window prevents the
        # later slots from ever starting.
        if is_restart and not self._allow_restart():
            logger.error(
                "Worker[%d] restart rate limit exceeded, "
                "not starting replacement",
                worker_id,
            )
            # Close old worker if still around
            if worker is not None:
                worker.close_pipe()
                worker.close_process_handle()
                worker = None
            self._workers[worker_id] = None
            return None

        self._generation += 1
        start_time = time.monotonic()

        new_worker = OcrWorkerProcess(
            worker_id=worker_id,
            generation=self._generation,
            config=self._config,
        )

        try:
            start_task = asyncio.create_task(
                asyncio.to_thread(new_worker.start),
                name=f"ocr-worker-start-{worker_id}-g{self._generation}",
            )
            try:
                await asyncio.shield(start_task)
            except asyncio.CancelledError:
                # ``to_thread`` cannot stop native model initialization.  Wait
                # for it to settle, then guarantee the process is cleaned up.
                try:
                    await asyncio.shield(start_task)
                except Exception:
                    pass
                await asyncio.to_thread(
                    new_worker.ensure_dead, self._config.kill_timeout,
                )
                new_worker.close_pipe()
                new_worker.close_process_handle()
                raise

            if is_restart:
                self._metrics.restarted += 1
                self._restart_times.append(time.monotonic())
            self._started_once[worker_id] = True

            # Close old worker
            if worker is not None:
                worker.close_pipe()
                worker.close_process_handle()

            self._workers[worker_id] = new_worker

            elapsed = time.monotonic() - start_time
            logger.info(
                "Worker[%d] %s g%d→g%d (pid=%d) in %.1fs",
                worker_id, "replaced" if is_restart else "started",
                worker.generation if worker else -1,
                self._generation, new_worker.pid, elapsed,
            )
            return new_worker

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._metrics.crashed += 1
            logger.error("Worker[%d] start failed: %s", worker_id, exc)
            try:
                await asyncio.to_thread(
                    new_worker.ensure_dead, self._config.kill_timeout,
                )
            except Exception:
                pass
            new_worker.close_pipe()
            new_worker.close_process_handle()
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

        limit = self._config.max_restarts_per_window
        return limit > 0 and len(self._restart_times) < limit

    async def _kill_worker(self, worker_id: int, *, count_crash: bool) -> None:
        """Kill a worker without blocking the event loop."""
        worker = self._workers[worker_id]
        if worker is not None:
            try:
                await asyncio.to_thread(
                    worker.ensure_dead, self._config.kill_timeout,
                )
            except Exception as exc:
                logger.warning("Worker[%d] ensure_dead error: %s", worker_id, exc)
            worker.close_pipe()
            worker.close_process_handle()
            if count_crash:
                self._metrics.crashed += 1
        self._workers[worker_id] = None

    async def _handle_worker_failure(
        self, worker_id: int, request_id: str, error: str,
    ) -> None:
        """Handle worker failure and fail the active task."""
        await self._kill_worker(worker_id, count_crash=True)
        self._fail_future(
            request_id,
            STABLE_ERROR_CODES["WORKER_CRASH"],
            error,
        )

    def _should_recycle_worker(self, worker: OcrWorkerProcess) -> bool:
        """Return True when configured lifecycle limits require recycling."""
        max_tasks = self._config.max_tasks_per_worker
        if max_tasks > 0 and worker.tasks_completed >= max_tasks:
            logger.info(
                "Worker[%d] reached max_tasks_per_worker=%d; recycling",
                worker.worker_id, max_tasks,
            )
            return True

        max_rss = self._config.max_rss_mb
        if max_rss > 0:
            rss = worker.rss_mb()
            if rss is not None and rss >= max_rss:
                logger.warning(
                    "Worker[%d] RSS %.1fMB reached limit %dMB; recycling",
                    worker.worker_id, rss, max_rss,
                )
                return True
        return False

    # ── Internal: Future management ─────────────────────────────────────────

    def _discard_pending_request(self, request_id: str) -> None:
        """Remove a request registered but not yet assigned to a worker."""
        entry = self._active_tasks.pop(request_id, None)
        if entry is not None and entry[1] < 0:
            self._metrics.queued = max(0, self._metrics.queued - 1)
        if entry is not None and not entry[0].done():
            entry[0].cancel()

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
                page_index=entry[2],
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
        request_id = uuid.uuid4().hex
        now = time.monotonic()

        return WorkerRequest(
            request_id=request_id,
            page_index=page_index,
            mode=mode,
            worker_generation=self._generation,
            submitted_monotonic=now,
            deadline_monotonic=now + self._config.total_deadline,
            # The hash was previously computed synchronously on the event loop
            # for every page but was never consumed by the worker or metrics.
            image_hash="",
            image_bytes=image_bytes,
            options=options or {},
        )
