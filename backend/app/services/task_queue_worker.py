"""Task queue worker — background processor for durable tasks.

Provides a high-level API to enqueue and process tasks from the
``DurableTaskQueue``. This module integrates the task queue with
the existing pipeline background functions.

Usage::

    # Enqueue (replaces asyncio.create_task)
    await enqueue_pipeline_task(pipeline_id, file_content, ...)

    # Run worker (in a background asyncio task)
    worker_task = asyncio.create_task(run_pipeline_worker())
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid

import redis.exceptions as redis_exc

from app.core.config import settings
from app.core.deployment_profile import DeploymentProfile, detect_deployment_profile
from app.services.db_fencing import FencingRejectedError
from app.services.staging_storage import (
    async_cleanup_work_copy,
    async_create_work_copy,
    async_lease_object,
    async_retrieve_file,
    async_touch_object,
)
from app.services.task_queue_service import (
    EnqueueResult,
    Task,
    TaskQueueUnavailableError,
    task_queue,
)
from app.services.worker_claimed_execution import run_claimed_task
from app.services.worker_legacy_handlers import (
    LegacyTaskContext,
    select_legacy_handler,
)
from app.services.worker_task_types import DISPATCHER_TASK_TYPES, REAPER_TASK_TYPES
from app.services.worker_v2_execution import run_v2_task

logger = logging.getLogger("postgraduate-ai.task-worker")


async def _init_fencing_for_task(task: Task, pipeline_id: str, task_type: str) -> None:
    """Initialize DB fencing fields on the business record for this task.

    Uses a conditional UPDATE to prevent TOCTOU — only sets fence fields
    if the current generation is lower (or None/0), ensuring a newer claim
    cannot be overwritten by a stale worker.

    Fencing failure here is non-fatal (logged) — the actual business writes
    will be guarded by verify_fencing_or_raise.
    """
    from app.core.database import async_session
    from app.services.db_fencing import FENCING_TABLES, initialize_fencing_fields

    table_entry = FENCING_TABLES.get(task_type)
    if table_entry is None:
        return

    model_class, id_column = table_entry
    try:
        async with async_session() as db:
            ok = await initialize_fencing_fields(
                db=db,
                model_class=model_class,
                record_id=pipeline_id,
                task_id=task.task_id,
                owner_token=task.owner_token,
                generation=task.generation,
                status="processing",
            )
            if ok:
                logger.debug(
                    "DB fencing initialized: task_id=%s model=%s id=%s gen=%d",
                    task.task_id,
                    model_class.__name__,
                    pipeline_id,
                    task.generation,
                )
            else:
                logger.warning(
                    "DB fencing init skipped (stale generation): task_id=%s gen=%d",
                    task.task_id,
                    task.generation,
                )
    except Exception as e:
        logger.warning(
            "DB fencing init failed (non-fatal): task_id=%s error=%s",
            task.task_id,
            e,
        )


async def _resolve_staging_path(
    staging_object_id: str, owner_token: str = "", generation: int = 0
) -> str:
    """Resolve a staging object ID to a work copy path in the scratch directory.

    Raises FileNotFoundError if the staging object does not exist.
    The returned path is a writable work copy in the worker scratch
    directory; the caller should call ``_cleanup_work_copy`` after
    processing is complete.

    Automatically acquires a lease on the staging object to prevent
    cleanup from deleting it while the worker is processing the task.
    The lease is tied to the task's owner_token and generation for
    fencing verification.
    """
    if not staging_object_id:
        raise FileNotFoundError("staging_object_id is empty")

    # Claim the lifecycle guard-backed lease *before* retrieving/copying.
    # Otherwise cleanup can delete the object in the gap between an existence
    # check and lease creation. lease_object itself verifies the data file.
    await async_lease_object(
        staging_object_id, owner_token=owner_token, generation=generation
    )

    staged_path = await async_retrieve_file(staging_object_id)
    if not staged_path:
        raise FileNotFoundError(
            f"Staging object {staging_object_id} not found after lease"
        )

    # Create a writable work copy so the pipeline can mutate it
    scratch_dir = _get_scratch_dir()
    work_path = await async_create_work_copy(staging_object_id, scratch_dir)
    return str(work_path)


async def _resolve_file_path(store: dict | None) -> str:
    """Resolve file path from pipeline store, preferring staging storage.

    Legacy fallback from ``_file_path`` has been removed — all production
    tasks must supply a ``staging_object_id``.

    If a ``staging_object_id`` is present, retrieves the file from staging.
    Returns empty string if not found.
    """
    if not store:
        return ""
    staging_id = store.get("staging_object_id")
    if staging_id:
        staged_path = await async_retrieve_file(staging_id)
        if staged_path:
            return staged_path
        logger.warning("Staging object %s not found", staging_id)
    return ""


def _get_scratch_dir() -> str:
    """Return the worker scratch directory, ensuring it exists."""
    from pathlib import Path

    scratch = getattr(settings, "WORKER_SCRATCH_DIR", "") or "/tmp/worker-scratch"
    Path(scratch).mkdir(parents=True, exist_ok=True)
    return scratch


async def _cleanup_work_copy(work_path: str | None) -> None:
    """Remove a work copy file created by _resolve_staging_path."""
    if work_path:
        await async_cleanup_work_copy(work_path)


async def _process_answer_projection_task(task: Task) -> None:
    """Project one committed per-answer PracticeRecord into derived state."""
    from app.core.database import async_session
    from app.services.practice.answer_projection_contract import (
        parse_answer_projection_payload,
    )
    from app.services.practice.answer_projection_service import project_practice_answer

    payload = parse_answer_projection_payload(task.payload)
    practice_record_id = payload.practice_record_id

    async with async_session() as db:
        result = await project_practice_answer(
            db,
            practice_record_id=practice_record_id,
            request_id=payload.request_id,
        )
    logger.info(
        "Answer projection task finished: task_id=%s record_id=%s processed=%s duplicate=%s",
        task.task_id,
        practice_record_id,
        result.get("processed"),
        result.get("duplicate", False),
    )


async def _process_error_diagnosis_task(task: Task) -> None:
    """Generate a non-blocking AI error-cause suggestion for one wrong event."""
    from app.core.database import async_session
    from app.services.error_diagnosis_service import generate_ai_suggestion

    payload = task.payload or {}
    diagnosis_id = int(payload.get("diagnosis_id") or 0)
    user_id = int(payload.get("user_id") or 0)
    classification_version = int(payload.get("classification_version") or 0)
    if diagnosis_id <= 0 or user_id <= 0 or classification_version <= 0:
        raise ValueError("invalid error_diagnosis task payload")
    async with async_session() as db:
        result = await generate_ai_suggestion(
            db,
            user_id=user_id,
            diagnosis_id=diagnosis_id,
            expected_classification_version=classification_version,
        )
    logger.info(
        "Error diagnosis task finished: task_id=%s diagnosis_id=%s result=%s",
        task.task_id,
        diagnosis_id,
        result,
    )


# ── task type constants ──

TASK_TYPE_IMPORT_PIPELINE = "import_pipeline"
TASK_TYPE_RESUME_PIPELINE = "resume_pipeline"
TASK_TYPE_ADMIN_RESUME = "admin_resume"
TASK_TYPE_IMAGE_PIPELINE = "image_pipeline"
TASK_TYPE_EXCEL_PIPELINE = "excel_pipeline"
TASK_TYPE_PREWARM_ANALYSIS = "prewarm_analysis"
TASK_TYPE_FORMULA_BATCH = "formula_batch"
TASK_TYPE_BATCH_IMAGE = "batch_image"
TASK_TYPE_ANSWER_PROJECTION = "answer_projection"
TASK_TYPE_ERROR_DIAGNOSIS = "error_diagnosis"

# Current worker version for rolling deployment compatibility.
# Must be incremented when backward-incompatible task processing changes are made.
_WORKER_VERSION: int = 2

# Task types that support DB fencing (have execution_generation columns)
_FENCING_TASK_TYPES = frozenset(
    {
        TASK_TYPE_IMPORT_PIPELINE,
        TASK_TYPE_IMAGE_PIPELINE,
        TASK_TYPE_EXCEL_PIPELINE,
        TASK_TYPE_RESUME_PIPELINE,
        TASK_TYPE_ADMIN_RESUME,
        TASK_TYPE_BATCH_IMAGE,
        # formula_batch excluded: processes multiple FormulaCard records,
        # no single business record to fence per task
    }
)


async def _check_worker_version_compatibility(task: Task) -> None:
    """Verify this worker is compatible with the task's minimum_worker_version.

    Raises:
        ValueError: If the worker version is too old for this task.
            The task should be marked as incompatible/dead, not retried.
    """
    required = getattr(task, "minimum_worker_version", 1)
    if required > _WORKER_VERSION:
        raise ValueError(
            f"Incompatible task payload version: task requires minimum_worker_version={required} "
            f"but current worker version is {_WORKER_VERSION}. "
            f"task_id={task.task_id} type={task.task_type} schema_version={task.schema_version}"
        )


# ── enqueue helpers ──

_LEASE_SEC = 600  # 10 minutes default lease

# Local development intentionally permits imports without Redis.  Production
# and cloud deployments remain fail-closed and continue to require the durable
# Redis queue.  Keep strong references to fallback tasks until completion;
# asyncio only keeps weak references to detached tasks.
_local_fallback_tasks: dict[str, asyncio.Task[None]] = {}
_LOCAL_FALLBACK_REASONS = frozenset({"redis_unavailable", "no_backend"})


def _can_use_local_execution_fallback() -> bool:
    """Return True only for the single-process/local import deployment profile."""
    if (settings.APP_ENV or "").strip().lower() == "production":
        return False
    try:
        return detect_deployment_profile() == DeploymentProfile.LOCAL_IMPORT
    except Exception:
        # Invalid/ambiguous deployment config must never become permissive.
        return False


async def _run_local_fallback_task(task: Task) -> None:
    """Execute a v2 task in-process when local development has no Redis.

    This is deliberately not a production durability substitute: there is no
    cross-process retry/lease persistence.  It exists so the documented local
    development profile can run imports without provisioning Redis.
    """
    logger.warning(
        "Running task via local in-process fallback: task_id=%s type=%s",
        task.task_id,
        task.task_type,
    )
    try:
        # Use the non-fenced single-process dispatcher. v2 fencing is for
        # cross-process Redis ownership and would be meaningless here.
        await _process_task(task)
    except asyncio.CancelledError:
        logger.info("Local fallback task cancelled: task_id=%s", task.task_id)
        raise
    except Exception:
        logger.exception(
            "Local fallback task failed: task_id=%s type=%s",
            task.task_id,
            task.task_type,
        )


def _schedule_local_fallback(
    *,
    task_type: str,
    payload: dict,
    task_id: str | None,
    max_retries: int,
) -> EnqueueResult:
    tid = task_id or f"task_{uuid.uuid4().hex}"

    existing = _local_fallback_tasks.get(tid)
    if existing is not None and not existing.done():
        return EnqueueResult(accepted=True, task_id=tid, reason="duplicate_local")

    try:
        from app.core.log_context import get_log_context

        _ctx = get_log_context()
    except Exception:
        _ctx = {}

    task = Task(
        task_id=tid,
        task_type=task_type,
        payload=payload,
        max_retries=max_retries,
        owner_token=f"local-{uuid.uuid4().hex}",
        generation=max(1, int(time.time() * 1000)),
        lease_expires_at=time.time() + _LEASE_SEC,
        trace_id=str(_ctx.get("trace_id") or ""),
        request_id=str(_ctx.get("request_id") or ""),
    )
    background = asyncio.create_task(
        _run_local_fallback_task(task),
        name=f"local-v2:{task_type}:{tid}",
    )
    _local_fallback_tasks[tid] = background

    def _discard(_task: asyncio.Task[None]) -> None:
        _local_fallback_tasks.pop(tid, None)

    background.add_done_callback(_discard)
    return EnqueueResult(accepted=True, task_id=tid, reason="local_fallback")


async def _enqueue_v2_with_local_fallback(
    task_type: str,
    payload: dict,
    *,
    task_id: str | None = None,
    max_retries: int = 2,
) -> EnqueueResult:
    """Use Redis v2 normally; fall back to detached local execution only in dev.

    Refresh staging retention before enqueueing. This is deliberately separate
    from worker ownership leases: touching metadata cannot overwrite an active
    worker's fenced lease when the same content-addressed object is reused.
    """
    staging_ids: list[str] = []
    single = payload.get("staging_object_id")
    if isinstance(single, str) and single:
        staging_ids.append(single)
    many = payload.get("staging_object_ids")
    if isinstance(many, list):
        staging_ids.extend(item for item in many if isinstance(item, str) and item)
    for object_id in dict.fromkeys(staging_ids):
        try:
            touched = await async_touch_object(object_id)
        except Exception as exc:
            logger.error(
                "Staging lifecycle coordination unavailable before enqueue: task=%s object=%s error=%s",
                task_id or "<generated>",
                object_id,
                exc,
            )
            return EnqueueResult(
                accepted=False,
                task_id=None,
                reason="staging_unavailable",
                retry_after=30,
            )
        if not touched:
            logger.warning(
                "Staging object missing/corrupt before enqueue: task=%s object=%s",
                task_id or "<generated>",
                object_id,
            )
            return EnqueueResult(
                accepted=False,
                task_id=None,
                reason="staging_object_missing",
                retry_after=0,
            )

    result = await task_queue.enqueue_v2(
        task_type,
        payload,
        task_id=task_id,
        max_retries=max_retries,
    )
    if result or result.reason not in _LOCAL_FALLBACK_REASONS:
        return result
    if not _can_use_local_execution_fallback():
        return result

    logger.warning(
        "Redis task queue unavailable; using local fallback: task_id=%s type=%s reason=%s",
        task_id or "<generated>",
        task_type,
        result.reason,
    )
    return _schedule_local_fallback(
        task_type=task_type,
        payload=payload,
        task_id=task_id,
        max_retries=max_retries,
    )


async def enqueue_import_pipeline(
    pipeline_id: str,
    staging_object_id: str,
    source_type: str,
    source_file: str,
    subject: str | None,
    subject_id: int | None,
    options: dict,
    created_by: str | None = None,
    source_sha256: str | None = None,
) -> EnqueueResult:
    """Enqueue an import pipeline task via the durable queue."""
    payload = {
        "pipeline_id": pipeline_id,
        "source_type": source_type,
        "source_file": source_file,
        "subject": subject,
        "subject_id": subject_id,
        "options": options,
        "created_by": created_by,
        "source_sha256": source_sha256,
        "staging_object_id": staging_object_id,
    }
    return await _enqueue_v2_with_local_fallback(
        TASK_TYPE_IMPORT_PIPELINE,
        payload,
        task_id=f"import:{pipeline_id}",
        max_retries=2,
    )


async def enqueue_resume_pipeline(
    pipeline_id: str,
    staging_object_id: str,
    subject: str | None,
    subject_id: int | None,
    options: dict,
) -> EnqueueResult:
    """Enqueue a pipeline resume task."""
    payload = {
        "pipeline_id": pipeline_id,
        "staging_object_id": staging_object_id,
        "subject": subject,
        "subject_id": subject_id,
        "options": options,
    }
    return await _enqueue_v2_with_local_fallback(
        TASK_TYPE_RESUME_PIPELINE,
        payload,
        task_id=f"resume:{pipeline_id}",
        max_retries=2,
    )


async def enqueue_image_pipeline(
    pipeline_id: str,
    staging_object_id: str,
    source_file: str,
    subject: str | None,
    subject_id: int | None,
    options: dict,
    created_by: str | None = None,
) -> EnqueueResult:
    """Enqueue an image OCR pipeline task."""
    payload = {
        "pipeline_id": pipeline_id,
        "source_file": source_file,
        "subject": subject,
        "subject_id": subject_id,
        "options": options,
        "created_by": created_by,
        "staging_object_id": staging_object_id,
    }
    return await _enqueue_v2_with_local_fallback(
        TASK_TYPE_IMAGE_PIPELINE,
        payload,
        task_id=f"image:{pipeline_id}",
        max_retries=2,
    )


async def enqueue_excel_pipeline(
    pipeline_id: str,
    staging_object_id: str,
    source_file: str,
    created_by: str | None = None,
) -> EnqueueResult:
    """Enqueue an Excel import pipeline task."""
    payload = {
        "pipeline_id": pipeline_id,
        "source_file": source_file,
        "created_by": created_by,
        "staging_object_id": staging_object_id,
    }
    return await _enqueue_v2_with_local_fallback(
        TASK_TYPE_EXCEL_PIPELINE,
        payload,
        task_id=f"excel:{pipeline_id}",
        max_retries=2,
    )


async def enqueue_formula_batch(
    job_id: str,
    card_ids: list[int],
    admin_id: int,
) -> EnqueueResult:
    """Enqueue a formula batch generation task."""
    payload = {
        "job_id": job_id,
        "card_ids": card_ids,
        "admin_id": admin_id,
    }
    return await _enqueue_v2_with_local_fallback(
        TASK_TYPE_FORMULA_BATCH,
        payload,
        task_id=f"formula_batch:{job_id}",
        max_retries=2,
    )


async def enqueue_admin_resume(
    pipeline_id: str,
    staging_object_id: str,
    source_type: str,
    source_file: str,
    subject: str | None,
    subject_id: int | None,
    options: dict,
) -> EnqueueResult:
    """Enqueue an admin resume pipeline task via the durable queue.

    Differs from ``enqueue_resume_pipeline`` in that it uses the full
    ``run_pipeline`` (with checkpoint) rather than chunk-level resume.
    """
    payload = {
        "pipeline_id": pipeline_id,
        "staging_object_id": staging_object_id,
        "source_type": source_type,
        "source_file": source_file,
        "subject": subject,
        "subject_id": subject_id,
        "options": options,
    }
    return await _enqueue_v2_with_local_fallback(
        TASK_TYPE_ADMIN_RESUME,
        payload,
        task_id=f"admin_resume:{pipeline_id}",
        max_retries=2,
    )


async def enqueue_batch_image_job(
    job_id: str,
    staging_object_ids: list[str],
    subject: str | None,
    subject_id: int | None,
    options: dict,
    concurrency: int = 2,
) -> EnqueueResult:
    """Enqueue a batch image import job via the durable queue.

    Each image's staging_object_id is passed in the payload so the
    worker can resolve files from staging storage regardless of
    process boundaries.
    """
    payload = {
        "job_id": job_id,
        "staging_object_ids": staging_object_ids,
        "subject": subject,
        "subject_id": subject_id,
        "options": options,
        "concurrency": concurrency,
    }
    return await _enqueue_v2_with_local_fallback(
        TASK_TYPE_BATCH_IMAGE,
        payload,
        task_id=f"batch_image:{job_id}",
        max_retries=1,
    )


# ── Worker metrics ──

queue_metrics: dict[str, int] = {
    "lease_renewal_failure": 0,
    "owner_fencing_rejected": 0,
    "duplicate_enqueue_prevented": 0,
    "reaper_reclaimed": 0,
    "queue_redis_failure": 0,
    "hard_deadline_exceeded": 0,
}

# 单任务处理墙钟硬上限：防止某个 await 无界挂起时 worker 卡死（心跳无限续租、
# reaper 永不回收）。取值需大于最慢合法任务（本地 600 页 PDF 约 ≤2h）。
_PROCESS_HARD_DEADLINE_SEC = 4 * 3600


# ── worker runner ──

_worker_running = False
_worker_draining = False
_worker_task: asyncio.Task | None = None
_reaper_task: asyncio.Task | None = None


async def _process_task(task: Task) -> None:
    """Dispatch a task to its handler based on task_type."""
    task_type = task.task_type
    payload = task.payload
    pipeline_id = payload.get("pipeline_id", task.task_id)

    logger.info(
        "Worker processing task: type=%s task_id=%s pipeline_id=%s",
        task_type,
        task.task_id,
        pipeline_id,
    )

    legacy_staging_work_copies: list[str] = []

    async def _resolve_legacy_staging(staging_id: str) -> str:
        if not staging_id:
            return ""
        work_path = await _resolve_staging_path(staging_id)
        legacy_staging_work_copies.append(work_path)
        return work_path

    context = LegacyTaskContext(
        task=task,
        payload=payload,
        pipeline_id=pipeline_id,
        resolve_staging=_resolve_legacy_staging,
        namespace=globals(),
    )
    try:
        handler = select_legacy_handler(task_type, globals())
        await handler(context)
    finally:
        for work_path in legacy_staging_work_copies:
            await async_cleanup_work_copy(work_path)


async def _cancel_supervised_tasks(
    cancel_monitor: asyncio.Task,
    heartbeat_task: asyncio.Task,
    processing_task: asyncio.Task,
) -> None:
    """Cancel the owner-loss monitor, heartbeat and any running processing task."""
    cancel_monitor.cancel()
    try:
        await cancel_monitor
    except asyncio.CancelledError:
        pass
    heartbeat_task.cancel()
    try:
        await heartbeat_task
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.warning("Heartbeat task raised after cancel: %s", e)

    if not processing_task.done():
        processing_task.cancel()
        try:
            await processing_task
        except (asyncio.CancelledError, Exception):
            pass


async def _complete_supervised_task(task: Task) -> None:
    """Complete a supervised task, counting owner-fencing rejections."""
    ok = await task_queue.complete(task)
    if ok:
        logger.info(
            "Task completed successfully: task_id=%s",
            task.task_id,
        )
    else:
        logger.warning(
            "Complete rejected (owner mismatch, fencing): task_id=%s",
            task.task_id,
        )
        queue_metrics["owner_fencing_rejected"] += 1


async def _fail_supervised_task(
    task: Task, error: Exception, owner_lost: asyncio.Event
) -> None:
    """Fail a supervised task unless the owner was lost mid-processing."""
    if owner_lost.is_set():
        logger.warning(
            "Owner lost during processing, skipping fail: task_id=%s",
            task.task_id,
        )
        queue_metrics["owner_fencing_rejected"] += 1
    else:
        ok = await task_queue.fail(task, str(error))
        if not ok:
            logger.warning(
                "Fail rejected (owner mismatch, fencing): task_id=%s",
                task.task_id,
            )
            queue_metrics["owner_fencing_rejected"] += 1


async def _dispatch_supervised_outcome(
    task: Task, processing_task: asyncio.Task, owner_lost: asyncio.Event
) -> None:
    """Route a settled processing task to completion or owner-loss handling."""
    was_cancelled = processing_task.cancelled()

    if was_cancelled or owner_lost.is_set():
        logger.warning(
            "Owner lost, skipping complete/fail: task_id=%s",
            task.task_id,
        )
        if was_cancelled:
            queue_metrics["owner_fencing_rejected"] += 1
    else:
        await _complete_supervised_task(task)


async def _settle_supervised_task(
    task: Task,
    task_type: str,
    processing_task: asyncio.Task,
    owner_lost: asyncio.Event,
    cancel_monitor: asyncio.Task,
    heartbeat_task: asyncio.Task,
) -> None:
    """Await processing, settle the outcome, then cancel supervised children."""
    try:
        try:
            await processing_task
        except asyncio.CancelledError:
            logger.warning(
                "Processing cancelled (owner lost): task_id=%s",
                task.task_id,
            )
            queue_metrics["owner_fencing_rejected"] += 1

        await _dispatch_supervised_outcome(task, processing_task, owner_lost)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.exception("Task failed: task_id=%s type=%s", task.task_id, task_type)
        await _fail_supervised_task(task, e, owner_lost)
    finally:
        await _cancel_supervised_tasks(cancel_monitor, heartbeat_task, processing_task)


async def _process_supervised_task(task: Task, task_type: str, lease_sec: int) -> None:
    """Run one claimed legacy task with heartbeat and owner-loss supervision."""
    owner_lost = asyncio.Event()
    heartbeat_task = asyncio.create_task(_heartbeat_loop(task, lease_sec, owner_lost))

    # Wrap processing in a cancellable task so owner loss terminates it
    processing_task = asyncio.create_task(_process_task(task))
    cancel_monitor = asyncio.create_task(
        _cancel_on_owner_loss(processing_task, owner_lost)
    )

    await _settle_supervised_task(
        task,
        task_type,
        processing_task,
        owner_lost,
        cancel_monitor,
        heartbeat_task,
    )


async def run_pipeline_worker(
    poll_interval: float = 5.0,
    lease_sec: int = _LEASE_SEC,
) -> None:
    """Run the import pipeline worker loop.

    Dequeues tasks, processes them with heartbeat, and handles
    completion/failure with retries.

    Handles ``CancelledError`` gracefully and resets the running
    flag in a ``finally`` block.
    """
    global _worker_running
    _worker_running = True

    task_types = DISPATCHER_TASK_TYPES

    logger.info("Pipeline worker started: polling every %ss", poll_interval)

    try:
        while _worker_running:
            processed = False
            for task_type in task_types:
                # When draining, stop claiming new tasks
                if _worker_draining:
                    logger.info("Worker draining — skipping dequeue")
                    await asyncio.sleep(1)
                    continue

                try:
                    task = await task_queue.dequeue(task_type, lease_sec=lease_sec)
                except Exception as e:
                    logger.warning("Dequeue failed for %s: %s", task_type, e)
                    continue

                if task is None:
                    continue

                processed = True
                await _process_supervised_task(task, task_type, lease_sec)

            if not processed:
                await asyncio.sleep(poll_interval)
    except asyncio.CancelledError:
        logger.info("Pipeline worker cancelled")
        raise
    finally:
        _worker_running = False
        logger.info("Pipeline worker stopped")


# ══════════════════════════════════════════════════════════════════════════════
# v2 Pipeline Worker — uses v2 queue with generation fencing
# ══════════════════════════════════════════════════════════════════════════════

_v2_worker_running = False
_v2_worker_draining = False
_v2_active_processing: set[asyncio.Task] = set()
"""Track active processing tasks spawned by the dispatcher. Used for shutdown coordination."""

_v2_primary_dispatcher_task: asyncio.Task | None = None
"""Reference to the dispatcher task itself, for signal-based cancellation."""


async def _verify_fencing_or_cancel(
    task: Task, pipeline_id: str, task_type: str
) -> None:
    """Verify DB fencing before business writes. Raises FencingRejectedError on mismatch."""
    from app.services.db_fencing import (
        FENCING_TABLES,
        FencingVerificationError,
        verify_fencing_or_raise,
    )

    table_entry = FENCING_TABLES.get(task_type)
    if table_entry is None:
        return

    from app.core.database import async_session

    try:
        async with async_session() as db:
            await verify_fencing_or_raise(
                db=db,
                model_class=table_entry[0],
                record_id=pipeline_id,
                expected_task_id=task.task_id,
                expected_generation=task.generation,
                expected_owner_token=task.owner_token,
            )
    except FencingVerificationError as e:
        logger.warning(
            "v2 Pre-execution fence check FAILED: task_id=%s pipeline_id=%s gen=%d — %s",
            task.task_id,
            pipeline_id,
            task.generation,
            e,
        )
        raise FencingRejectedError(str(e)) from e
    except Exception as e:
        logger.warning(
            "v2 Pre-execution fence check error (non-fatal): task_id=%s error=%s",
            task.task_id,
            e,
        )
        raise


async def _process_task_v2(task: Task) -> None:
    """Process a task with generation and owner_token context.

    Sets a fencing context via contextvars so that ``update_pipeline_status``
    in the call chain automatically uses atomic fenced UPDATEs instead of
    plain UPDATEs.

    Raises:
        ValueError: If worker version is incompatible with task payload.
    """
    from app.features.pipeline_checkpoint import (
        clear_fencing_context,
        set_fencing_context,
    )

    return await run_v2_task(
        task,
        namespace=globals(),
        set_context=set_fencing_context,
        clear_context=clear_fencing_context,
    )


async def _try_claim_any_v2(task_types: list[str], lease_sec: int) -> Task | None:
    """Try to claim a task from any of the given task types. Returns first available.

    Returns None only when all queues are genuinely empty.
    Raises TaskQueueUnavailableError when Redis is unreachable.
    """
    for task_type in task_types:
        try:
            task = await task_queue.dequeue_v2(task_type, lease_sec=lease_sec)
            if task is not None:
                return task
        except TaskQueueUnavailableError:
            raise
        except Exception as e:
            logger.warning("v2 Dequeue failed for %s: %s", task_type, e)
    return None


async def _complete_with_retry_v2(task: Task, max_attempts: int = 3) -> int:
    """Retry the terminal completion transition while the lease heartbeat is alive."""
    for attempt in range(1, max_attempts + 1):
        try:
            return await task_queue.complete_v2(task)
        except TaskQueueUnavailableError as exc:
            if attempt >= max_attempts:
                raise
            delay = min(max(float(exc.retry_after), 0.1) * attempt, 5.0)
            logger.warning(
                "v2 Complete transition unavailable; retrying: task_id=%s attempt=%d/%d delay=%.1fs",
                task.task_id,
                attempt,
                max_attempts,
                delay,
            )
            await asyncio.sleep(delay)
    return 0


async def _fail_with_retry_v2(task: Task, error: str, max_attempts: int = 3) -> int:
    """Retry the atomic fail/retry/dead transition without mutating task ownership."""
    for attempt in range(1, max_attempts + 1):
        try:
            return await task_queue.fail_v2(task, error)
        except TaskQueueUnavailableError as exc:
            if attempt >= max_attempts:
                raise
            delay = min(max(float(exc.retry_after), 0.1) * attempt, 5.0)
            logger.warning(
                "v2 Fail transition unavailable; retrying: task_id=%s attempt=%d/%d delay=%.1fs",
                task.task_id,
                attempt,
                max_attempts,
                delay,
            )
            await asyncio.sleep(delay)
    return 0


async def _process_claimed_task_v2(
    task: Task, lease_sec: int, sem: asyncio.Semaphore
) -> None:
    """Process a claimed v2 task with heartbeat, cancellation, and lifecycle.

    Holds the semaphore slot for the duration of processing.
    Releases the semaphore and cleans up work copy on completion.

    The caller (*run_dispatcher_v2*) acquires the semaphore before claiming
    the task. The semaphore is released in this function's ``finally`` block.
    """
    from app.core.log_context import (
        bind_log_context,
        generate_request_id,
        generate_trace_id,
        reset_log_context,
    )

    return await run_claimed_task(
        task,
        lease_sec,
        sem,
        namespace=globals(),
        bind_context=bind_log_context,
        generate_request_id=generate_request_id,
        generate_trace_id=generate_trace_id,
        reset_context=reset_log_context,
    )


async def _probe_v2_redis_recovery(backoff: float) -> None:
    """Sleep in five-second steps while waiting for Redis to recover.

    The fragmented sleep keeps graceful shutdown responsive during the
    circuit-breaker probe window.
    """
    _probe_target = min(backoff * 2, 300)
    _probe_step = 5
    _probe_waited = 0
    while (
        _probe_waited < _probe_target and _v2_worker_running and not _v2_worker_draining
    ):
        await asyncio.sleep(min(_probe_step, _probe_target - _probe_waited))
        _probe_waited += _probe_step


async def _handle_v2_redis_failure(
    error: TaskQueueUnavailableError,
    failure_count: int,
    max_failures: int = 10,
) -> int:
    """Back off after a Redis failure and return the new consecutive count."""
    failure_count += 1
    queue_metrics["queue_redis_failure"] += 1
    backoff = min(error.retry_after * (1 << min(failure_count - 1, 4)), 300)
    logger.error(
        "v2 Dispatcher Redis unavailable (failure #%d): %s — backing off %ds",
        failure_count,
        error,
        backoff,
    )
    if failure_count >= max_failures:
        logger.critical(
            "v2 Dispatcher circuit breaker OPEN after %d Redis failures — "
            "entering degraded probe mode (worker stays alive, retries periodically)",
            failure_count,
        )
        # 熔断后不退出循环：退出会让 worker 进程存活但不领任务（半死）、
        # 队列持续堆积直到人工重启。降级为周期探测 Redis，恢复后自动重入。
        # 分段 sleep 期间检查 draining，保证 graceful shutdown 及时生效。
        await _probe_v2_redis_recovery(backoff)
    else:
        await asyncio.sleep(backoff)
    return failure_count


def _spawn_v2_processing(
    task: Task, lease_sec: int, semaphore: asyncio.Semaphore
) -> None:
    """Spawn background processing; it releases the semaphore on completion."""
    proc_task = asyncio.create_task(
        _process_claimed_task_v2(task, lease_sec, semaphore),
        name=f"proc:{task.task_id}",
    )
    _v2_active_processing.add(proc_task)
    proc_task.add_done_callback(_v2_active_processing.discard)


async def _run_dispatcher_v2_loop(
    task_types: list[str],
    semaphore: asyncio.Semaphore,
    poll_interval: float,
    lease_sec: int,
) -> None:
    """Run the v2 claim/spawn loop until draining, cancellation or stop."""
    _redis_failure_count = 0
    _max_redis_failures = 10

    while _v2_worker_running and not _v2_worker_draining:
        # 1. Wait for an available slot before claiming
        await semaphore.acquire()

        if _v2_worker_draining or not _v2_worker_running:
            semaphore.release()
            break

        # 2. Claim one task (any type)
        try:
            task = await _try_claim_any_v2(task_types, lease_sec)
        except TaskQueueUnavailableError as e:
            semaphore.release()
            _redis_failure_count = await _handle_v2_redis_failure(
                e, _redis_failure_count, _max_redis_failures
            )
            continue

        _redis_failure_count = 0

        if task is None:
            # No task available — release slot and sleep
            semaphore.release()
            await asyncio.sleep(poll_interval)
            continue

        # 3. Spawn background processing — task releases sem on completion
        _spawn_v2_processing(task, lease_sec, semaphore)

        # Yield control briefly so the just-created task can start
        await asyncio.sleep(0)


async def run_dispatcher_v2(
    poll_interval: float = 5.0,
    lease_sec: int = _LEASE_SEC,
) -> None:
    """v2 Dispatcher — semaphore-based concurrency control.

    Waits for an available slot (asyncio.Semaphore), THEN claims one task.
    Never claims multiple tasks and waits for the semaphore inside processing.

    Concurrency is controlled by ``WORKER_CONCURRENCY`` in settings
    (default: 1). With concurrency=1, at most one heavy task is in
    processing+executing at any time across all task types.

    Designed as a replacement for ``run_pipeline_worker_v2`` which used
    sequential per-type polling without concurrency management.
    """
    global _v2_worker_running
    _v2_worker_running = True

    from app.core.worker_concurrency import get_worker_semaphore

    semaphore = await get_worker_semaphore()

    task_types = DISPATCHER_TASK_TYPES

    logger.info(
        "v2 Dispatcher started: concurrency=%d poll=%ss",
        settings.WORKER_CONCURRENCY,
        poll_interval,
    )

    try:
        await _run_dispatcher_v2_loop(task_types, semaphore, poll_interval, lease_sec)
    except asyncio.CancelledError:
        logger.info("v2 Dispatcher cancelled")
        raise
    finally:
        _v2_worker_running = False
        logger.info("v2 Dispatcher stopped")


async def _v2_heartbeat_cancel_requested(
    task: Task, owner_lost: asyncio.Event | None
) -> bool:
    """Check the task hash for a cancel request; failures stay non-fatal."""
    try:
        task_data = await task_queue.get_task_v2(task.task_id)
    except Exception:
        return False  # Cancel check failure is non-fatal for heartbeat
    if task_data and task_data.get("cancel_requested") == "1":
        logger.warning(
            "v2 Cancel requested, stopping: task_id=%s reason=%s",
            task.task_id,
            task_data.get("cancel_reason", ""),
        )
        if owner_lost is not None:
            owner_lost.set()
        return True
    return False


def _abandon_v2_heartbeat(
    owner_lost: asyncio.Event | None, message: str, *args
) -> None:
    """Log a heartbeat failure, count it and mark the owner as lost."""
    logger.warning(message, *args)
    queue_metrics["lease_renewal_failure"] += 1
    if owner_lost is not None:
        owner_lost.set()


async def _retry_v2_heartbeat_once(
    task: Task,
    lease_sec: int,
    interval: int,
    owner_lost: asyncio.Event | None,
) -> bool:
    """Retry the heartbeat once after a transient error; True means recovered."""
    try:
        await asyncio.sleep(1)
        ok = await task_queue.heartbeat_v2(task, lease_sec=lease_sec)
        if ok == 1:
            await asyncio.sleep(interval)
            return True
    except Exception:
        pass

    _abandon_v2_heartbeat(
        owner_lost,
        "v2 Heartbeat retry failed, owner lost: task_id=%s",
        task.task_id,
    )
    return False


async def _v2_heartbeat_tick(
    task: Task,
    lease_sec: int,
    interval: int,
    owner_lost: asyncio.Event | None,
) -> bool:
    """Run one heartbeat cycle; True continues the loop, False stops it."""
    try:
        ok = await task_queue.heartbeat_v2(task, lease_sec=lease_sec)
        if ok == 1:
            if await _v2_heartbeat_cancel_requested(task, owner_lost):
                return False
            await asyncio.sleep(interval)
            return True
        _abandon_v2_heartbeat(
            owner_lost,
            "v2 Heartbeat rejected (code=%d), owner lost: task_id=%s",
            ok,
            task.task_id,
        )
        return False
    except (redis_exc.ConnectionError, redis_exc.TimeoutError) as exc:
        lease_window_remaining = task.lease_expires_at - time.time()
        if lease_window_remaining < interval * 2:
            _abandon_v2_heartbeat(
                owner_lost,
                "v2 Heartbeat transient error + short lease window (%.1fs < %ds), "
                "owner lost: task_id=%s error=%s",
                lease_window_remaining,
                interval * 2,
                task.task_id,
                exc,
            )
            return False
        logger.warning(
            "v2 Heartbeat transient error, retrying once: task_id=%s error=%s",
            task.task_id,
            exc,
        )
        return await _retry_v2_heartbeat_once(task, lease_sec, interval, owner_lost)
    except asyncio.CancelledError:
        return False
    except Exception as exc:
        _abandon_v2_heartbeat(
            owner_lost,
            "v2 Heartbeat unexpected error, owner lost: task_id=%s error=%s",
            task.task_id,
            exc,
        )
        return False


async def _v2_heartbeat_loop_with_lease_window(
    task: Task,
    lease_sec: int,
    owner_lost: asyncio.Event | None = None,
) -> None:
    """Heartbeat loop with lease-window-aware failure detection.

    On explicit Lua rejection (owner or generation mismatch):
        → owner-lost immediately.

    On transient error (connection/timeout):
        If lease_window_remaining < heartbeat_interval * 2 → owner-lost.
        Otherwise → retry once, then owner-lost if still failing.

    Once owner_lost is set, the heartbeat loop stops and does NOT
    attempt further heartbeats. The caller is responsible for handling
    the owner-lost event.
    """
    interval = max(lease_sec // 3, 10)
    while _v2_worker_running:
        if not await _v2_heartbeat_tick(task, lease_sec, interval, owner_lost):
            break


async def set_draining_v2() -> None:
    """Set draining mode for v2 worker — stop claiming, finish current tasks."""
    global _v2_worker_draining
    _v2_worker_draining = True
    logger.info("v2 Pipeline worker draining — no new tasks claimed")


def is_draining_v2() -> bool:
    """Return whether v2 worker is draining."""
    return _v2_worker_draining


async def stop_worker_v2() -> None:
    """Signal the v2 dispatcher loop to stop."""
    global _v2_worker_running
    _v2_worker_running = False
    logger.info("v2 Pipeline worker stopping")


async def graceful_shutdown_v2(grace_sec: int | None = None) -> None:
    """Graceful shutdown for v2 worker: drain → shield → cancel.

    Shutdown order (enforced):
    1. Set draining — dispatcher stops claiming new tasks
    2. Shield active processing tasks during grace period
    3. After grace period expires, cancel remaining processing tasks
    4. Signal dispatcher to stop (running flag = False)

    The caller (main.py) then cancels the dispatcher task itself and
    proceeds with infrastructure shutdown (Redis, DB, httpx, etc.).

    This function does NOT close infrastructure resources — only
    coordinates in-flight task lifecycle.
    """
    if grace_sec is None:
        from app.core.config import settings

        grace_sec = getattr(settings, "WORKER_SHUTDOWN_GRACE_SEC", 30)
    else:
        grace_sec = max(grace_sec, 5)

    # Step 1: Stop claiming
    await set_draining_v2()
    logger.info(
        "v2 Graceful shutdown: draining set, waiting up to %ds for %d active tasks",
        grace_sec,
        len(_v2_active_processing),
    )

    if not _v2_active_processing:
        await stop_worker_v2()
        logger.info("v2 Graceful shutdown: no active tasks, stopped immediately")
        return

    # Step 2-3: Shield active tasks during grace period, then cancel
    try:
        await asyncio.wait_for(
            asyncio.gather(*_v2_active_processing, return_exceptions=True),
            timeout=grace_sec,
        )
        logger.info("v2 Graceful shutdown: all active tasks completed within grace")
    except TimeoutError:
        remaining = [t for t in list(_v2_active_processing) if not t.done()]
        if remaining:
            logger.warning(
                "v2 Graceful shutdown: grace period expired, cancelling %d active tasks",
                len(remaining),
            )
            for t in remaining:
                t.cancel()
            await asyncio.gather(*remaining, return_exceptions=True)
            logger.info("v2 Graceful shutdown: remaining tasks cancelled")

    # Step 4: Signal dispatcher to stop
    await stop_worker_v2()


async def _cancel_on_owner_loss(
    processing_task: asyncio.Task,
    owner_lost: asyncio.Event,
) -> None:
    """Wait for owner loss, then cancel the processing task.

    This ensures that when heartbeat fails (owner token mismatch),
    the in-flight processing is terminated rather than allowed to
    continue and potentially write stale results.
    """
    try:
        await owner_lost.wait()
        processing_task.cancel()
    except asyncio.CancelledError:
        pass


async def _heartbeat_loop(
    task: Task, lease_sec: int, owner_lost: asyncio.Event | None = None
) -> None:
    """Periodically extend task lease while worker is alive.

    Sets *owner_lost* event if heartbeat fails (owner token mismatch),
    signaling the main loop to stop processing and skip complete.
    """
    interval = max(lease_sec // 3, 10)
    while _worker_running:
        try:
            ok = await task_queue.heartbeat(task, lease_sec=lease_sec)
            if not ok:
                logger.warning(
                    "Heartbeat rejected (owner lost), halting: task_id=%s",
                    task.task_id,
                )
                queue_metrics["lease_renewal_failure"] += 1
                if owner_lost is not None:
                    owner_lost.set()
                break
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            break
        except Exception:
            break


async def set_draining() -> None:
    """Set draining mode — worker finishes current tasks but stops claiming new ones."""
    global _worker_draining
    _worker_draining = True
    logger.info("Pipeline worker draining — no new tasks will be claimed")


def is_draining() -> bool:
    """Return whether the worker is in draining mode.

    Used by the readiness probe to return 503 when draining.
    """
    return _worker_draining


async def stop_worker() -> None:
    """Signal the worker loop to stop."""
    global _worker_running
    _worker_running = False
    logger.info("Pipeline worker stopping")


# ── reaper runner ──

_reaper_running = False


async def run_reaper_loop(
    task_types: list[str] | None = None,
    interval: int = 60,
) -> None:
    """Run the reaper loop: reclaim expired leases.

    Handles ``CancelledError`` gracefully and resets the running
    flag in a ``finally`` block.
    """
    global _reaper_running
    _reaper_running = True

    types = task_types or REAPER_TASK_TYPES

    try:
        while _reaper_running:
            try:
                await task_queue.run_reaper(types)
            except Exception as e:
                logger.warning("Reaper cycle failed: %s", e)
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        logger.info("Reaper cancelled")
        raise
    finally:
        _reaper_running = False


async def stop_reaper() -> None:
    """Signal the reaper loop to stop."""
    global _reaper_running
    _reaper_running = False


# ── v2 reaper runner ──

_v2_reaper_running = False


async def run_reaper_loop_v2(
    task_types: list[str] | None = None,
    interval: int = 60,
) -> None:
    """Run the v2 reaper loop: reclaim expired leases from v2 keys."""
    global _v2_reaper_running
    _v2_reaper_running = True

    types = task_types or REAPER_TASK_TYPES

    try:
        while _v2_reaper_running:
            try:
                for tt in types:
                    await task_queue._reclaim_expired_v2(tt)
            except Exception as e:
                logger.warning("v2 Reaper cycle failed: %s", e)
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        logger.info("v2 Reaper cancelled")
        raise
    finally:
        _v2_reaper_running = False


async def stop_reaper_v2() -> None:
    """Signal the v2 reaper loop to stop."""
    global _v2_reaper_running
    _v2_reaper_running = False
