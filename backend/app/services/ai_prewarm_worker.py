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
import hashlib
import logging
import time

from app.ai.prompts import AI_ANALYSIS_PROMPT_VERSION
from app.services.task_queue_service import Task, TaskQueueUnavailableError, task_queue

logger = logging.getLogger(__name__)

TASK_TYPE_PREWARM = "prewarm_analysis"
_DEFAULT_LEASE_SEC = 240  # comfortably above the 150s wrong-analysis provider budget
_HEARTBEAT_INTERVAL = 30
_LOCAL_FALLBACK_MAX_TASKS = 100
_LOCAL_FALLBACK_CONCURRENCY = 2
_LOCAL_FALLBACK_MAX_RETRIES = 2
_LOCAL_FALLBACK_RECOVERY_MAX_RETRIES = 7
_PREWARM_INPUT_FAILURE_CODES = {
    "vision_input_missing",
    "vision_parse_failed",
    "vision_unavailable",
}

_worker_running = False
_worker_task: asyncio.Task | None = None
_local_fallback_tasks: dict[str, asyncio.Task] = {}
_local_fallback_semaphore: asyncio.Semaphore | None = None


# ── Public API ──


def build_prewarm_revision(
    *, review_count: int | None, wrong_answer: str | None
) -> str:
    """Stable, non-sensitive revision for one wrong-question state.

    The durable queue keeps idempotency keys for seven days. A fixed task id such
    as ``prewarm:{wq_id}`` therefore suppresses legitimate regeneration when the
    same question is answered incorrectly again within that window. Include the
    wrong-question revision in the task id while hashing the answer so no user
    content is exposed in Redis keys/logs.
    """
    raw = f"{AI_ANALYSIS_PROMPT_VERSION}|{int(review_count or 0)}|{wrong_answer or ''}"
    state_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:14]
    return f"r{int(review_count or 0)}:{state_hash}"


def _get_local_fallback_semaphore() -> asyncio.Semaphore:
    global _local_fallback_semaphore
    if _local_fallback_semaphore is None:
        _local_fallback_semaphore = asyncio.Semaphore(_LOCAL_FALLBACK_CONCURRENCY)
    return _local_fallback_semaphore


def _schedule_local_fallback(
    *,
    task_id: str,
    wq_id: int,
    user_id: int,
    revision: str | None,
    delay_seconds: int = 0,
    recovery_mode: bool = False,
    force_regenerate: bool = False,
    baseline_generated_at: str | None = None,
) -> bool:
    """Best-effort in-process prewarm when Redis is unavailable.

    The durable Redis queue remains the primary path.  In single-instance or
    temporarily degraded deployments, rejecting every prewarm task makes the
    optimization disappear entirely.  This bounded fallback keeps the user
    experience benefit without turning a Redis outage into unbounded local
    work.  Tasks are revision-deduplicated and limited to two concurrent LLM
    calls; they are intentionally not durable across process restarts.
    """

    existing = _local_fallback_tasks.get(task_id)
    if existing is not None and not existing.done():
        logger.info("[prewarm] local duplicate task_id=%s", task_id)
        return True

    # Drop completed entries before enforcing the bounded backlog.
    for key, task in list(_local_fallback_tasks.items()):
        if task.done():
            _local_fallback_tasks.pop(key, None)
    if len(_local_fallback_tasks) >= _LOCAL_FALLBACK_MAX_TASKS:
        logger.warning(
            "[prewarm] local fallback full wq_id=%d uid=%d backlog=%d",
            wq_id,
            user_id,
            len(_local_fallback_tasks),
        )
        return False

    async def runner() -> None:
        from app.services.ai_service import (
            PrewarmAnalysisError,
            prewarm_wrong_question_analysis,
        )

        try:
            if delay_seconds > 0:
                await asyncio.sleep(delay_seconds)
            async with _get_local_fallback_semaphore():
                started = time.monotonic()
                attempt = 0
                max_local_retries = (
                    _LOCAL_FALLBACK_RECOVERY_MAX_RETRIES
                    if recovery_mode
                    else _LOCAL_FALLBACK_MAX_RETRIES
                )
                while True:
                    logger.info(
                        "[prewarm] local start wq_id=%d uid=%d revision=%s attempt=%d",
                        wq_id,
                        user_id,
                        revision or "legacy",
                        attempt + 1,
                    )
                    try:
                        outcome = await prewarm_wrong_question_analysis(
                            wq_id,
                            user_id,
                            expected_revision=revision,
                            force_regenerate=force_regenerate,
                            baseline_generated_at=baseline_generated_at,
                        )
                        status = str(outcome.get("status") or "success")
                        logger.info(
                            "[prewarm] local %s wq_id=%d uid=%d duration_ms=%d",
                            status,
                            wq_id,
                            user_id,
                            int((time.monotonic() - started) * 1000),
                        )
                        break
                    except PrewarmAnalysisError as exc:
                        if exc.retryable and attempt < max_local_retries:
                            attempt += 1
                            backoff = min(2**attempt, 30)
                            logger.warning(
                                "[prewarm] local retry wq_id=%d uid=%d attempt=%d/%d "
                                "delay_sec=%d error_code=%s recovery=%s",
                                wq_id,
                                user_id,
                                attempt,
                                max_local_retries,
                                backoff,
                                exc.error_code,
                                recovery_mode,
                            )
                            await asyncio.sleep(backoff)
                            continue

                        category = (
                            "failed_input"
                            if exc.error_code in _PREWARM_INPUT_FAILURE_CODES
                            else "failed_permanent"
                            if not exc.retryable
                            else "failed_transient_exhausted"
                        )
                        logger.warning(
                            "[prewarm] local %s wq_id=%d uid=%d error_code=%s "
                            "retryable=%s attempts=%d duration_ms=%d",
                            category,
                            wq_id,
                            user_id,
                            exc.error_code,
                            exc.retryable,
                            attempt + 1,
                            int((time.monotonic() - started) * 1000),
                        )
                        break
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "[prewarm] local failed_unexpected wq_id=%d uid=%d",
                wq_id,
                user_id,
                exc_info=True,
            )
        finally:
            _local_fallback_tasks.pop(task_id, None)

    try:
        task = asyncio.create_task(runner(), name=f"ai-prewarm-local:{wq_id}")
    except RuntimeError:
        return False
    _local_fallback_tasks[task_id] = task
    logger.info(
        "[prewarm] local fallback scheduled wq_id=%d uid=%d task_id=%s",
        wq_id,
        user_id,
        task_id,
    )
    return True


async def enqueue_prewarm(
    wq_id: int,
    user_id: int,
    retries: int = 0,
    delay_seconds: int = 0,
    revision: str | None = None,
    *,
    recovery_mode: bool = False,
    force_regenerate: bool = False,
    baseline_generated_at: str | None = None,
    task_id_override: str | None = None,
    max_retries_override: int | None = None,
) -> bool:
    """Enqueue a prewarm analysis task via the durable task queue.

    Returns True if the task was accepted (queued or idempotent duplicate).
    If Redis is unavailable, a bounded in-process fallback is used so prewarm
    still works on a single healthy web instance.  The local path is best
    effort and intentionally not durable across process restarts.
    """
    payload = {
        "wq_id": wq_id,
        "user_id": user_id,
    }
    if revision:
        payload["revision"] = revision
    if recovery_mode:
        payload["recovery_mode"] = True
    if force_regenerate:
        payload["force_regenerate"] = True
    if baseline_generated_at is not None:
        payload["baseline_generated_at"] = str(baseline_generated_at)[:128]
    # A normal revisioned id deduplicates the same answer event across direct
    # submit + projection fallback. Recovery calls use a caller-supplied unique
    # id so repeated manual regenerations are never suppressed by the 7-day
    # idempotency tombstone.
    task_id = task_id_override or f"prewarm:{wq_id}:{revision or 'legacy'}"

    max_retries = (
        max(1, int(max_retries_override))
        if max_retries_override is not None
        else max(0, 3 - retries)
    )
    # If delay > 0, don't use idempotent key (it may be a retry)
    result = await task_queue.enqueue_v2(
        TASK_TYPE_PREWARM,
        payload,
        task_id=task_id,
        max_retries=max_retries,
        idempotent=(delay_seconds == 0),
    )

    if not result.accepted:
        if result.reason == "redis_unavailable":
            accepted_local = _schedule_local_fallback(
                task_id=task_id,
                wq_id=wq_id,
                user_id=user_id,
                revision=revision,
                delay_seconds=delay_seconds,
                recovery_mode=recovery_mode,
                force_regenerate=force_regenerate,
                baseline_generated_at=baseline_generated_at,
            )
            logger.warning(
                "[prewarm] Redis unavailable; local_fallback=%s wq_id=%d uid=%d retries=%d",
                accepted_local,
                wq_id,
                user_id,
                retries,
            )
            return accepted_local
        logger.warning(
            "[prewarm] queue rejected wq_id=%d uid=%d retries=%d reason=%s",
            wq_id,
            user_id,
            retries,
            result.reason or "unknown",
        )
        return False

    logger.info(
        "[prewarm] enqueued wq_id=%d uid=%d retries=%d task_id=%s",
        wq_id,
        user_id,
        retries,
        task_id,
    )
    return True


async def enqueue_prewarm_batch(
    wrong_question_ids: list[int],
    user_id: int,
    *,
    revisions: dict[int, str] | None = None,
) -> dict[str, list[int]]:
    """Queue a completed practice's wrong questions as one best-effort batch.

    Duplicate wrong-question ids are removed while preserving their original
    order. Queue writes remain independent, so one unavailable item never
    prevents the remaining analyses from being scheduled.
    """
    unique_ids = list(
        dict.fromkeys(int(wq_id) for wq_id in wrong_question_ids if wq_id)
    )
    queued: list[int] = []
    skipped: list[int] = []

    for wq_id in unique_ids:
        try:
            accepted = await enqueue_prewarm(
                wq_id, user_id, revision=(revisions or {}).get(wq_id)
            )
        except Exception:
            logger.warning(
                "[prewarm] batch enqueue failed wq_id=%d uid=%d",
                wq_id,
                user_id,
                exc_info=True,
            )
            accepted = False
        (queued if accepted else skipped).append(wq_id)

    logger.info(
        "[prewarm] practice batch scheduled uid=%d queued=%d skipped=%d",
        user_id,
        len(queued),
        len(skipped),
    )
    return {"queued": queued, "skipped": skipped}


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

    from app.core.worker_concurrency import get_worker_semaphore
    from app.services.ai_service import PrewarmAnalysisError

    semaphore = await get_worker_semaphore()

    logger.info(
        "[prewarm] worker started (poll=%ss lease=%ds)", poll_interval, lease_sec
    )

    _redis_failure_count = 0

    try:
        while _worker_running:
            # Acquire shared worker concurrency slot before claiming
            await semaphore.acquire()
            try:
                task = await task_queue.dequeue_v2(
                    TASK_TYPE_PREWARM, lease_sec=lease_sec
                )
            except TaskQueueUnavailableError as e:
                _redis_failure_count += 1
                backoff = min(
                    e.retry_after * (1 << min(_redis_failure_count - 1, 4)), 300
                )
                logger.error(
                    "[prewarm] Redis unavailable (failure #%d): %s — backing off %ds",
                    _redis_failure_count,
                    e,
                    backoff,
                )
                semaphore.release()
                await asyncio.sleep(backoff)
                continue
            except Exception as e:
                logger.warning("[prewarm] dequeue failed: %s", e)
                semaphore.release()
                await asyncio.sleep(poll_interval)
                continue

            _redis_failure_count = 0

            if task is None:
                semaphore.release()
                await asyncio.sleep(poll_interval)
                continue

            from app.core.log_context import (
                bind_log_context,
                generate_request_id,
                generate_trace_id,
                reset_log_context,
            )

            log_tokens = bind_log_context(
                trace_id=task.trace_id or generate_trace_id("tr_prewarm"),
                request_id=task.request_id or generate_request_id("req_prewarm"),
                job_id=task.task_id,
                user_id=task.payload.get("user_id"),
            )
            try:
                heartbeat_task = asyncio.create_task(_heartbeat_loop(task, lease_sec))

                try:
                    outcome = await _process_task(task)
                    ok = await task_queue.complete_v2(task)
                    if not ok:
                        logger.warning(
                            "[prewarm] complete rejected (owner mismatch): task_id=%s",
                            task.task_id,
                        )
                    else:
                        logger.info(
                            "[prewarm] %s wq_id=%s uid=%s",
                            str(outcome.get("status") or "success"),
                            task.payload.get("wq_id"),
                            task.payload.get("user_id"),
                        )
                except PrewarmAnalysisError as exc:
                    if not exc.retryable:
                        # Force the durable queue directly into its dead-letter
                        # branch: auth/config/input failures will not recover by
                        # replaying the exact same payload.
                        task.max_retries = task.retry_count + 1

                    fail_result = await task_queue.fail_v2(
                        task, f"{exc.error_code}: {exc.model}"
                    )
                    task_status = str(getattr(task.status, "value", task.status or ""))
                    dead_lettered = fail_result == 2 or task_status == "dead"

                    if not exc.retryable:
                        category = (
                            "failed_input"
                            if exc.error_code in _PREWARM_INPUT_FAILURE_CODES
                            else "failed_permanent"
                        )
                        if dead_lettered:
                            logger.warning(
                                "[prewarm] %s wq_id=%s uid=%s error_code=%s retryable=false",
                                category,
                                task.payload.get("wq_id"),
                                task.payload.get("user_id"),
                                exc.error_code,
                            )
                        else:
                            logger.warning(
                                "[prewarm] permanent fail rejected task_id=%s result=%s status=%s error_code=%s",
                                task.task_id,
                                fail_result,
                                task_status,
                                exc.error_code,
                            )
                    elif dead_lettered:
                        logger.warning(
                            "[prewarm] failed_transient_exhausted wq_id=%s uid=%s "
                            "error_code=%s retry_count=%d",
                            task.payload.get("wq_id"),
                            task.payload.get("user_id"),
                            exc.error_code,
                            task.retry_count,
                        )
                    elif fail_result == 1:
                        logger.warning(
                            "[prewarm] retry wq_id=%s uid=%s error_code=%s retry_count=%d/%d",
                            task.payload.get("wq_id"),
                            task.payload.get("user_id"),
                            exc.error_code,
                            task.retry_count,
                            task.max_retries,
                        )
                    else:
                        logger.warning(
                            "[prewarm] fail rejected (owner/generation mismatch): task_id=%s",
                            task.task_id,
                        )
                except Exception as e:
                    logger.exception(
                        "[prewarm] failed_unexpected task_id=%s",
                        task.task_id,
                    )
                    fail_result = await task_queue.fail_v2(task, str(e))
                    task_status = str(getattr(task.status, "value", task.status or ""))
                    if fail_result == 2 or task_status == "dead":
                        logger.warning(
                            "[prewarm] failed_unexpected_exhausted task_id=%s",
                            task.task_id,
                        )
                    elif fail_result == 1:
                        logger.warning(
                            "[prewarm] retry_unexpected task_id=%s retry_count=%d/%d",
                            task.task_id,
                            task.retry_count,
                            task.max_retries,
                        )
                    elif not fail_result:
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
            finally:
                reset_log_context(log_tokens)
                semaphore.release()

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


async def _process_task(task: Task) -> dict:
    """Execute a single prewarm analysis task and return its terminal outcome."""
    from app.services.ai_service import prewarm_wrong_question_analysis

    wq_id = task.payload.get("wq_id")
    user_id = task.payload.get("user_id")

    if not wq_id or not user_id:
        logger.warning("[prewarm] invalid task payload: %s", task.payload)
        return {"status": "skipped", "reason": "invalid_payload"}

    queue_wait_ms = max(
        0, int((time.time() - float(task.created_at or time.time())) * 1000)
    )
    logger.info(
        "[prewarm] start wq_id=%d uid=%d revision=%s queue_wait_ms=%d",
        wq_id,
        user_id,
        task.payload.get("revision") or "legacy",
        queue_wait_ms,
    )
    return await prewarm_wrong_question_analysis(
        wq_id,
        user_id,
        expected_revision=task.payload.get("revision"),
        force_regenerate=bool(task.payload.get("force_regenerate")),
        baseline_generated_at=task.payload.get("baseline_generated_at"),
    )


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
    local_tasks = list(_local_fallback_tasks.values())
    for task in local_tasks:
        if not task.done():
            task.cancel()
    if local_tasks:
        await asyncio.gather(*local_tasks, return_exceptions=True)
        _local_fallback_tasks.clear()
    if _worker_task is None:
        return
    _worker_task.cancel()
    try:
        await _worker_task
    except asyncio.CancelledError:
        pass
    _worker_task = None
    logger.info("[prewarm] worker terminated")
