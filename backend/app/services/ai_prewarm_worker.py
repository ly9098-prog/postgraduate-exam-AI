"""AI prewarm worker — durable task queue backed, replaces BLPOP-based implementation.

Migrated from the previous custom Redis List + BLPOP + manual retry ZSET
to the shared DurableTaskQueue providing atomic Lua operations, owner
fencing, lease-based heartbeat, retry/dead-letter, and crash recovery.

Usage:
    enqueue_prewarm(wq_id=123, user_id=456)  # push to durable queue
    # Worker loop runs in lifespan (worker role)
"""

from __future__ import annotations

import asyncio
import logging

from app.services.task_queue_service import Task, TaskQueueUnavailableError, task_queue

logger = logging.getLogger(__name__)

TASK_TYPE_PREWARM = "prewarm_analysis"
_DEFAULT_LEASE_SEC = 120  # 2 minutes — AI analysis is usually fast
_HEARTBEAT_INTERVAL = 30

_worker_running = False
_worker_task: asyncio.Task | None = None


# ── Public API ──


async def enqueue_prewarm(
    wq_id: int,
    user_id: int,
    retries: int = 0,
    delay_seconds: int = 0,
) -> bool:
    """Enqueue a prewarm analysis task via the durable task queue.

    Returns True if the task was accepted (queued or idempotent duplicate).
    Returns False if the queue is unavailable (no Redis in production =
    503 to the caller).
    """
    payload = {
        "wq_id": wq_id,
        "user_id": user_id,
    }
    task_id = f"prewarm:{wq_id}"

    max_retries = max(0, 3 - retries)  # remaining retries from current count
    # If delay > 0, don't use idempotent key (it may be a retry)
    result = await task_queue.enqueue_v2(
        TASK_TYPE_PREWARM,
        payload,
        task_id=task_id,
        max_retries=max_retries,
        idempotent=(delay_seconds == 0),
    )

    if not result.accepted:
        logger.warning(
            "[prewarm] queue rejected wq_id=%d uid=%d retries=%d (Redis unavailable)",
            wq_id, user_id, retries,
        )
        return False

    logger.info(
        "[prewarm] enqueued wq_id=%d uid=%d retries=%d task_id=%s",
        wq_id, user_id, retries, task_id,
    )
    return True


# ── Worker loop ──


async def run_prewarm_worker(
    poll_interval: float = 3.0,
    lease_sec: int = _DEFAULT_LEASE_SEC,
) -> None:
    """Run the prewarm analysis worker loop.

    Dequeues tasks from the durable queue, processes them with heartbeat,
    and handles completion/failure with DurableTaskQueue retry logic.
    """
    global _worker_running
    _worker_running = True

    logger.info("[prewarm] worker started (poll=%ss lease=%ds)", poll_interval, lease_sec)

    _redis_failure_count = 0

    try:
        while _worker_running:
            try:
                task = await task_queue.dequeue_v2(TASK_TYPE_PREWARM, lease_sec=lease_sec)
            except TaskQueueUnavailableError as e:
                _redis_failure_count += 1
                backoff = min(e.retry_after * (1 << min(_redis_failure_count - 1, 4)), 300)
                logger.error(
                    "[prewarm] Redis unavailable (failure #%d): %s — backing off %ds",
                    _redis_failure_count, e, backoff,
                )
                await asyncio.sleep(backoff)
                continue
            except Exception as e:
                logger.warning("[prewarm] dequeue failed: %s", e)
                await asyncio.sleep(poll_interval)
                continue

            _redis_failure_count = 0

            if task is None:
                await asyncio.sleep(poll_interval)
                continue

            # Process task with heartbeat loop
            heartbeat_task = asyncio.create_task(
                _heartbeat_loop(task, lease_sec)
            )

            try:
                await _process_task(task)
                ok = await task_queue.complete_v2(task)
                if not ok:
                    logger.warning(
                        "[prewarm] complete rejected (owner mismatch): task_id=%s",
                        task.task_id,
                    )
                else:
                    logger.info(
                        "[prewarm] completed wq_id=%s uid=%s",
                        task.payload.get("wq_id"), task.payload.get("user_id"),
                    )
            except Exception as e:
                logger.exception(
                    "[prewarm] processing failed: task_id=%s", task.task_id,
                )
                ok = await task_queue.fail_v2(task, str(e))
                if not ok:
                    logger.warning(
                        "[prewarm] fail rejected (owner mismatch): task_id=%s",
                        task.task_id,
                    )
            finally:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass

    except asyncio.CancelledError:
        logger.info("[prewarm] worker cancelled")
        raise
    finally:
        _worker_running = False
        logger.info("[prewarm] worker stopped")


async def _heartbeat_loop(task: Task, lease_sec: int) -> None:
    """Periodically extend task lease while the worker is alive."""
    interval = max(lease_sec // 3, 10)
    while _worker_running:
        try:
            ok = await task_queue.heartbeat_v2(task, lease_sec=lease_sec)
            if not ok:
                logger.warning(
                    "[prewarm] heartbeat rejected (owner lost): task_id=%s",
                    task.task_id,
                )
                break
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            break
        except Exception:
            break


async def _process_task(task: Task) -> None:
    """Execute a single prewarm analysis task."""
    from app.services.ai_service import prewarm_wrong_question_analysis

    wq_id = task.payload.get("wq_id")
    user_id = task.payload.get("user_id")

    if not wq_id or not user_id:
        logger.warning("[prewarm] invalid task payload: %s", task.payload)
        return

    await prewarm_wrong_question_analysis(wq_id, user_id)
    logger.info("[prewarm] processed wq_id=%d uid=%d", wq_id, user_id)


# ── Lifecycle ──


async def start_worker():
    """Start the background prewarm worker. Call in FastAPI lifespan startup."""
    global _worker_task
    if _worker_task is not None:
        return
    _worker_task = asyncio.create_task(run_prewarm_worker(), name="ai-prewarm-worker")


async def stop_worker():
    """Stop the background prewarm worker. Call in FastAPI lifespan shutdown."""
    global _worker_task, _worker_running
    _worker_running = False
    if _worker_task is None:
        return
    _worker_task.cancel()
    try:
        await _worker_task
    except asyncio.CancelledError:
        pass
    _worker_task = None
    logger.info("[prewarm] worker terminated")
