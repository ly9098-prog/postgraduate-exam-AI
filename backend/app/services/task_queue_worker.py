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

import redis.exceptions as redis_exc

from app.core.config import settings
from app.services.db_fencing import FencingRejectedError
from app.services.staging_storage import (
    async_cleanup_work_copy,
    async_create_work_copy,
    async_lease_object,
    async_retrieve_file,
)
from app.services.task_queue_service import (
    EnqueueResult,
    Task,
    TaskQueueUnavailableError,
    task_queue,
)

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
                    task.task_id, model_class.__name__, pipeline_id, task.generation,
                )
            else:
                logger.warning(
                    "DB fencing init skipped (stale generation): task_id=%s gen=%d",
                    task.task_id, task.generation,
                )
    except Exception as e:
        logger.warning(
            "DB fencing init failed (non-fatal): task_id=%s error=%s",
            task.task_id, e,
        )


async def _resolve_staging_path(staging_object_id: str, owner_token: str = "", generation: int = 0) -> str:
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

    # Verify the staging object exists
    staged_path = await async_retrieve_file(staging_object_id)
    if not staged_path:
        raise FileNotFoundError(f"Staging object {staging_object_id} not found")

    # Acquire lease with owner+generation to prevent cleanup during processing
    await async_lease_object(staging_object_id, owner_token=owner_token, generation=generation)

    # Create a writable work copy so the pipeline can mutate it
    scratch_dir = _get_scratch_dir()
    work_path = await async_create_work_copy(staging_object_id, scratch_dir)
    return str(work_path)


async def _resolve_file_path(store: dict | None) -> EnqueueResult:
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


# ── task type constants ──

TASK_TYPE_IMPORT_PIPELINE = "import_pipeline"
TASK_TYPE_RESUME_PIPELINE = "resume_pipeline"
TASK_TYPE_ADMIN_RESUME = "admin_resume"
TASK_TYPE_IMAGE_PIPELINE = "image_pipeline"
TASK_TYPE_EXCEL_PIPELINE = "excel_pipeline"
TASK_TYPE_PREWARM_ANALYSIS = "prewarm_analysis"
TASK_TYPE_FORMULA_BATCH = "formula_batch"
TASK_TYPE_BATCH_IMAGE = "batch_image"

# Current worker version for rolling deployment compatibility.
# Must be incremented when backward-incompatible task processing changes are made.
_WORKER_VERSION: int = 1

# Task types that support DB fencing (have execution_generation columns)
_FENCING_TASK_TYPES = frozenset({
    TASK_TYPE_IMPORT_PIPELINE,
    TASK_TYPE_IMAGE_PIPELINE,
    TASK_TYPE_EXCEL_PIPELINE,
    TASK_TYPE_RESUME_PIPELINE,
    TASK_TYPE_ADMIN_RESUME,
    TASK_TYPE_BATCH_IMAGE,
    # formula_batch excluded: processes multiple FormulaCard records,
    # no single business record to fence per task
})


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


async def enqueue_import_pipeline(
    pipeline_id: str,
    staging_object_id: str,
    source_type: str,
    source_file: str,
    subject: str | None,
    subject_id: int | None,
    options: dict,
    created_by: str | None = None,
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
        "staging_object_id": staging_object_id,
    }
    return await task_queue.enqueue_v2(
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
    return await task_queue.enqueue_v2(
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
) -> EnqueueResult:
    """Enqueue an image OCR pipeline task."""
    payload = {
        "pipeline_id": pipeline_id,
        "source_file": source_file,
        "subject": subject,
        "subject_id": subject_id,
        "options": options,
        "staging_object_id": staging_object_id,
    }
    return await task_queue.enqueue_v2(
        TASK_TYPE_IMAGE_PIPELINE,
        payload,
        task_id=f"image:{pipeline_id}",
        max_retries=2,
    )


async def enqueue_excel_pipeline(
    pipeline_id: str,
    staging_object_id: str,
    source_file: str,
) -> EnqueueResult:
    """Enqueue an Excel import pipeline task."""
    payload = {
        "pipeline_id": pipeline_id,
        "source_file": source_file,
        "staging_object_id": staging_object_id,
    }
    return await task_queue.enqueue_v2(
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
    return await task_queue.enqueue_v2(
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
    return await task_queue.enqueue_v2(
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
    return await task_queue.enqueue_v2(
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
}


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
        task_type, task.task_id, pipeline_id,
    )

    if task_type == TASK_TYPE_IMPORT_PIPELINE:
        from app.services.import_pipeline_service import _run_pipeline_with_db

        staging_id = payload.get("staging_object_id", "")
        file_path = await _resolve_staging_path(staging_id) if staging_id else ""
        await _run_pipeline_with_db(
            pipeline_id=pipeline_id,
            file_path=file_path,
            source_type=payload.get("source_type", "pdf"),
            source_file=payload.get("source_file", ""),
            subject=payload.get("subject"),
            subject_id=payload.get("subject_id"),
            options=payload.get("options", {}),
            created_by=payload.get("created_by"),
        )

    elif task_type == TASK_TYPE_IMAGE_PIPELINE:
        from app.services.import_pipeline_service import _run_image_pipeline_with_db

        staging_id = payload.get("staging_object_id", "")
        image_path = await _resolve_staging_path(staging_id) if staging_id else ""
        if not image_path:
            raise FileNotFoundError(f"Staging object {staging_id} not found for image pipeline")
        await _run_image_pipeline_with_db(
            pipeline_id=pipeline_id,
            image_path=image_path,
            source_file=payload.get("source_file", ""),
            subject=payload.get("subject"),
            subject_id=payload.get("subject_id"),
            options=payload.get("options", {}),
        )

    elif task_type == TASK_TYPE_EXCEL_PIPELINE:
        from app.features.pipeline_orchestrator import run_excel_pipeline_background

        staging_id = payload.get("staging_object_id", "")
        file_path = await _resolve_staging_path(staging_id) if staging_id else ""
        file_content = b""
        if file_path:
            with open(file_path, "rb") as _fh:
                file_content = _fh.read()
        from app.features import question_pipeline as pipeline_svc

        await run_excel_pipeline_background(
            pipeline_id=pipeline_id,
            file_content=file_content,
            source_file=payload.get("source_file", ""),
            import_excel_fn=pipeline_svc.import_excel,
        )

    elif task_type == TASK_TYPE_RESUME_PIPELINE:
        from app.services.import_pipeline_service import run_resume_background

        staging_id = payload.get("staging_object_id", "")
        file_path = await _resolve_staging_path(staging_id) if staging_id else ""
        await run_resume_background(
            pipeline_id=pipeline_id,
            file_path=file_path,
            subject=payload.get("subject"),
            subject_id=payload.get("subject_id"),
            options=payload.get("options", {}),
        )

    elif task_type == TASK_TYPE_ADMIN_RESUME:
        from app.core.database import async_session
        from app.features.pipeline_coordinator_entry import run_pipeline
        from app.features.pipeline_orchestrator import (
            _get_stage_checkpoint,
            _set_pipeline_store,
        )

        staging_id = payload.get("staging_object_id", "")
        file_path = await _resolve_staging_path(staging_id) if staging_id else ""
        source_type = payload.get("source_type", "pdf")
        source_file = payload.get("source_file", "")
        subject = payload.get("subject")
        subject_id = payload.get("subject_id")
        opts = payload.get("options", {})

        # Re-read checkpoint from shared Redis (cross-process accessible)
        ckpt = await _get_stage_checkpoint(pipeline_id)

        async with async_session() as resume_db:
            result = await run_pipeline(
                file_path=file_path,
                source_type=source_type,
                source_file=source_file,
                subject=subject,
                subject_id=subject_id,
                options=opts,
                db=resume_db,
                pipeline_id=pipeline_id,
                resume_from_checkpoint=ckpt,
            )
        # Store result in pipeline store for status polling
        try:
            await _set_pipeline_store(pipeline_id, result)
        except Exception:
            logger.warning("Failed to store admin resume result for %s", pipeline_id)

    elif task_type == TASK_TYPE_FORMULA_BATCH:
        from sqlalchemy import select

        from app.core.database import async_session
        from app.models.formula import FormulaCard
        from app.services.formula_graph_spec_service import _process_batch

        card_ids = payload.get("card_ids", [])
        admin_id = payload.get("admin_id", 0)
        job_id = payload.get("job_id", "")

        async with async_session() as db:
            result = await db.execute(
                select(FormulaCard).where(FormulaCard.id.in_(card_ids))
            )
            cards = list(result.scalars().all())

        await _process_batch(job_id, cards, admin_id)

    elif task_type == TASK_TYPE_BATCH_IMAGE:
        from app.features import batch_image_import_service as batch_svc
        from app.services.staging_storage import retrieve_file

        job_id = payload.get("job_id", "")
        staging_ids: list[str] = payload.get("staging_object_ids", [])
        subject = payload.get("subject")
        subject_id = payload.get("subject_id")
        options = payload.get("options", {})
        concurrency = payload.get("concurrency", 2)

        # Reconstruct BatchImageSource from staging object IDs
        sources: list[batch_svc.BatchImageSource] = []
        for idx, staging_id in enumerate(staging_ids):
            if not staging_id:
                logger.warning(
                    "Empty staging_object_id for batch image seq=%d job=%s",
                    idx + 1, job_id,
                )
                continue
            file_path = retrieve_file(staging_id)
            if not file_path:
                logger.warning(
                    "Staging object %s not found for batch image seq=%d job=%s",
                    staging_id, idx + 1, job_id,
                )
                continue
            sources.append(batch_svc.BatchImageSource(
                seq=idx + 1,
                source_file=f"image_{idx + 1}.png",
                temp_path=file_path,
            ))

        if not sources:
            logger.error("No valid sources found for batch image job %s", job_id)
            return

        await batch_svc.run_batch_job(
            job_id=job_id,
            sources=sources,
            subject=subject,
            subject_id=subject_id,
            options=options,
            concurrency=concurrency,
        )

    else:
        logger.warning("Unknown task type: %s", task_type)


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

    task_types = [
        TASK_TYPE_IMPORT_PIPELINE,
        TASK_TYPE_IMAGE_PIPELINE,
        TASK_TYPE_EXCEL_PIPELINE,
        TASK_TYPE_RESUME_PIPELINE,
        TASK_TYPE_ADMIN_RESUME,
        TASK_TYPE_BATCH_IMAGE,
        TASK_TYPE_FORMULA_BATCH,
    ]

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
                owner_lost = asyncio.Event()
                heartbeat_task = asyncio.create_task(
                    _heartbeat_loop(task, lease_sec, owner_lost)
                )

                # Wrap processing in a cancellable task so owner loss terminates it
                processing_task = asyncio.create_task(_process_task(task))
                cancel_monitor = asyncio.create_task(
                    _cancel_on_owner_loss(processing_task, owner_lost)
                )

                try:
                    try:
                        await processing_task
                    except asyncio.CancelledError:
                        logger.warning(
                            "Processing cancelled (owner lost): task_id=%s",
                            task.task_id,
                        )
                        queue_metrics["owner_fencing_rejected"] += 1

                    was_cancelled = processing_task.cancelled()

                    if was_cancelled or owner_lost.is_set():
                        logger.warning(
                            "Owner lost, skipping complete/fail: task_id=%s",
                            task.task_id,
                        )
                        if was_cancelled:
                            queue_metrics["owner_fencing_rejected"] += 1
                    else:
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
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.exception(
                        "Task failed: task_id=%s type=%s", task.task_id, task_type
                    )
                    if owner_lost.is_set():
                        logger.warning(
                            "Owner lost during processing, skipping fail: task_id=%s",
                            task.task_id,
                        )
                        queue_metrics["owner_fencing_rejected"] += 1
                    else:
                        ok = await task_queue.fail(task, str(e))
                        if not ok:
                            logger.warning(
                                "Fail rejected (owner mismatch, fencing): task_id=%s",
                                task.task_id,
                            )
                            queue_metrics["owner_fencing_rejected"] += 1
                finally:
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


async def _verify_fencing_or_cancel(task: Task, pipeline_id: str, task_type: str) -> None:
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
            task.task_id, pipeline_id, task.generation, e,
        )
        raise FencingRejectedError(str(e)) from e
    except Exception as e:
        logger.warning(
            "v2 Pre-execution fence check error (non-fatal): task_id=%s error=%s",
            task.task_id, e,
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

    # Check worker-task version compatibility at entry
    await _check_worker_version_compatibility(task)

    task_type = task.task_type
    payload = task.payload
    pipeline_id = payload.get("pipeline_id", task.task_id)

    # Compute the actual DB record ID for fencing verification.
    _fence_record_id: str = ""
    if task_type in (TASK_TYPE_IMPORT_PIPELINE, TASK_TYPE_IMAGE_PIPELINE,
                     TASK_TYPE_EXCEL_PIPELINE, TASK_TYPE_RESUME_PIPELINE,
                     TASK_TYPE_ADMIN_RESUME):
        _fence_record_id = pipeline_id
    elif task_type == TASK_TYPE_BATCH_IMAGE:
        _fence_record_id = payload.get("job_id", "")

    logger.info(
        "Worker v2 processing: type=%s task_id=%s pipeline_id=%s gen=%d",
        task_type, task.task_id, pipeline_id, task.generation,
    )

    # Initialize DB fencing and set fencing context
    if _fence_record_id and task_type in _FENCING_TASK_TYPES:
        await _init_fencing_for_task(task, _fence_record_id, task_type)

    _fence_token = None
    if _fence_record_id and task_type in _FENCING_TASK_TYPES:
        _fence_token = set_fencing_context(
            task_id=task.task_id,
            owner_token=task.owner_token,
            generation=task.generation,
        )

    try:
        if task_type == TASK_TYPE_IMPORT_PIPELINE:
            from app.services.import_pipeline_service import _run_pipeline_with_db

            if _fence_record_id:
                await _verify_fencing_or_cancel(task, _fence_record_id, task_type)
            staging_id = payload.get("staging_object_id", "")
            file_path = await _resolve_staging_path(staging_id, task.owner_token, task.generation) if staging_id else ""
            await _run_pipeline_with_db(
                pipeline_id=pipeline_id,
                file_path=file_path,
                source_type=payload.get("source_type", "pdf"),
                source_file=payload.get("source_file", ""),
                subject=payload.get("subject"),
                subject_id=payload.get("subject_id"),
                options=payload.get("options", {}),
                created_by=payload.get("created_by"),
            )

        elif task_type == TASK_TYPE_IMAGE_PIPELINE:
            from app.services.import_pipeline_service import _run_image_pipeline_with_db

            staging_id = payload.get("staging_object_id", "")
            image_path = await _resolve_staging_path(staging_id, task.owner_token, task.generation) if staging_id else ""
            if not image_path:
                raise FileNotFoundError(f"Staging object {staging_id} not found for image pipeline")

            if _fence_record_id:
                await _verify_fencing_or_cancel(task, _fence_record_id, task_type)
            await _run_image_pipeline_with_db(
                pipeline_id=pipeline_id,
                image_path=image_path,
                source_file=payload.get("source_file", ""),
                subject=payload.get("subject"),
                subject_id=payload.get("subject_id"),
                options=payload.get("options", {}),
            )

        elif task_type == TASK_TYPE_EXCEL_PIPELINE:
            from app.features.pipeline_orchestrator import run_excel_pipeline_background

            staging_id = payload.get("staging_object_id", "")
            file_path = await _resolve_staging_path(staging_id, task.owner_token, task.generation) if staging_id else ""
            file_content = b""
            if file_path:
                with open(file_path, "rb") as _fh:
                    file_content = _fh.read()
            from app.features import question_pipeline as pipeline_svc

            if _fence_record_id:
                await _verify_fencing_or_cancel(task, _fence_record_id, task_type)
            await run_excel_pipeline_background(
                pipeline_id=pipeline_id,
                file_content=file_content,
                source_file=payload.get("source_file", ""),
                import_excel_fn=pipeline_svc.import_excel,
            )

        elif task_type == TASK_TYPE_RESUME_PIPELINE:
            from app.services.import_pipeline_service import run_resume_background

            staging_id = payload.get("staging_object_id", "")
            file_path = await _resolve_staging_path(staging_id, task.owner_token, task.generation) if staging_id else ""
            if _fence_record_id:
                await _verify_fencing_or_cancel(task, _fence_record_id, task_type)
            await run_resume_background(
                pipeline_id=pipeline_id,
                file_path=file_path,
                subject=payload.get("subject"),
                subject_id=payload.get("subject_id"),
                options=payload.get("options", {}),
            )

        elif task_type == TASK_TYPE_ADMIN_RESUME:
            from app.core.database import async_session
            from app.features.pipeline_coordinator_entry import run_pipeline
            from app.features.pipeline_orchestrator import (
                _get_stage_checkpoint,
                _set_pipeline_store,
            )

            staging_id = payload.get("staging_object_id", "")
            file_path = await _resolve_staging_path(staging_id, task.owner_token, task.generation) if staging_id else ""
            source_type = payload.get("source_type", "pdf")
            source_file = payload.get("source_file", "")
            subject = payload.get("subject")
            subject_id = payload.get("subject_id")
            opts = payload.get("options", {})

            ckpt = await _get_stage_checkpoint(pipeline_id)

            if _fence_record_id:
                await _verify_fencing_or_cancel(task, _fence_record_id, task_type)
            async with async_session() as resume_db:
                result = await run_pipeline(
                    file_path=file_path,
                    source_type=source_type,
                    source_file=source_file,
                    subject=subject,
                    subject_id=subject_id,
                    options=opts,
                    db=resume_db,
                    pipeline_id=pipeline_id,
                    resume_from_checkpoint=ckpt,
                )
            try:
                await _set_pipeline_store(pipeline_id, result)
            except Exception:
                logger.warning("Failed to store admin resume result for %s", pipeline_id)

        elif task_type == TASK_TYPE_FORMULA_BATCH:
            from sqlalchemy import select

            from app.core.database import async_session
            from app.models.formula import FormulaCard
            from app.services.formula_graph_spec_service import _process_batch

            card_ids = payload.get("card_ids", [])
            admin_id = payload.get("admin_id", 0)
            job_id = payload.get("job_id", "")

            async with async_session() as db:
                result = await db.execute(
                    select(FormulaCard).where(FormulaCard.id.in_(card_ids))
                )
                cards = list(result.scalars().all())

            await _process_batch(job_id, cards, admin_id)

        elif task_type == TASK_TYPE_BATCH_IMAGE:
            from app.features import batch_image_import_service as batch_svc
            from app.services.staging_storage import retrieve_file

            job_id = payload.get("job_id", "")
            staging_ids: list[str] = payload.get("staging_object_ids", [])
            subject = payload.get("subject")
            subject_id = payload.get("subject_id")
            options = payload.get("options", {})
            concurrency = payload.get("concurrency", 2)

            if _fence_record_id:
                await _verify_fencing_or_cancel(task, _fence_record_id, task_type)

            scratch_dir = _get_scratch_dir()
            work_copies: list[str] = []

            sources: list[batch_svc.BatchImageSource] = []
            for idx, staging_id in enumerate(staging_ids):
                if not staging_id:
                    continue
                file_path = retrieve_file(staging_id)
                if not file_path:
                    continue
                try:
                    work_path = str(await async_create_work_copy(staging_id, scratch_dir))
                    work_copies.append(work_path)
                except Exception as e:
                    logger.warning(
                        "Failed to create work copy for %s: %s, using original",
                        staging_id, e,
                    )
                    work_path = file_path
                sources.append(batch_svc.BatchImageSource(
                    seq=idx + 1,
                    source_file=f"image_{idx + 1}.png",
                    temp_path=work_path,
                ))

            if not sources:
                logger.error("No valid sources for batch image job %s", job_id)
                return

            try:
                await batch_svc.run_batch_job(
                    job_id=job_id,
                    sources=sources,
                    subject=subject,
                    subject_id=subject_id,
                    options=options,
                    concurrency=concurrency,
                )
            finally:
                for wp in work_copies:
                    await async_cleanup_work_copy(wp)

        else:
            # Unknown task type — dead-letter immediately, don't retry or complete
            logger.warning("Unknown task type %s — marking as dead-letter: task_id=%s",
                           task_type, task.task_id)
            task.max_retries = 0
            raise ValueError(f"unknown_task_type: {task_type}")

    finally:
        if _fence_token is not None:
            clear_fencing_context(_fence_token)

    # ── Post-execution atomic fence check ──
    # After business writes complete but before complete_v2, verify the fence
    # is still held via a conditional UPDATE. If rowcount=0, the fence was lost
    # during execution — raise FencingRejectedError to prevent complete_v2.
    if _fence_record_id and task_type in _FENCING_TASK_TYPES:
        from app.core.database import async_session
        from app.services.db_fencing import (
            FENCING_TABLES,
            FencingRejectedError,
            conditional_update_with_fencing,
        )

        table_entry = FENCING_TABLES.get(task_type)
        if table_entry is not None:
            model_class, _id_col = table_entry
            try:
                async with async_session() as db:
                    ok = await conditional_update_with_fencing(
                        db=db,
                        model_class=model_class,
                        record_id=_fence_record_id,
                        expected_task_id=task.task_id,
                        expected_generation=task.generation,
                        expected_owner_token=task.owner_token,
                        execution_status="completed",
                    )
                    if not ok:
                        await db.rollback()
                        raise FencingRejectedError(
                            f"Post-execution fence lost: "
                            f"model={model_class.__name__} id={_fence_record_id} "
                            f"task_id={task.task_id} gen={task.generation}"
                        )
                    await db.commit()
            except FencingRejectedError:
                raise
            except Exception as e:
                logger.warning(
                    "Post-execution fence check failed (non-fatal): "
                    "task_id=%s error=%s", task.task_id, e,
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


async def _process_claimed_task_v2(task: Task, lease_sec: int, sem: asyncio.Semaphore) -> None:
    """Process a claimed v2 task with heartbeat, cancellation, and lifecycle.

    Holds the semaphore slot for the duration of processing.
    Releases the semaphore and cleans up work copy on completion.

    The caller (*run_dispatcher_v2*) acquires the semaphore before claiming
    the task. The semaphore is released in this function's ``finally`` block.
    """
    owner_lost = asyncio.Event()

    hb_task = asyncio.create_task(
        _v2_heartbeat_loop_with_lease_window(task, lease_sec, owner_lost)
    )
    process_task = asyncio.create_task(_process_task_v2(task))
    cancel_watcher = asyncio.create_task(
        _cancel_on_owner_loss(process_task, owner_lost)
    )

    try:
        try:
            await process_task
        except asyncio.CancelledError:
            logger.warning(
                "v2 Processing cancelled (owner lost): task_id=%s", task.task_id,
            )
            queue_metrics["owner_fencing_rejected"] += 1

        was_cancelled = process_task.cancelled()

        if was_cancelled or owner_lost.is_set():
            if was_cancelled:
                logger.warning(
                    "v2 Owner lost, skipping complete/fail: task_id=%s", task.task_id,
                )
        else:
            try:
                ok = await task_queue.complete_v2(task)
                if ok == 1:
                    logger.info("v2 Task completed: task_id=%s", task.task_id)
                elif ok == 0:
                    logger.warning(
                        "v2 Complete owner mismatch: task_id=%s", task.task_id,
                    )
                    queue_metrics["owner_fencing_rejected"] += 1
                elif ok == -1:
                    logger.warning(
                        "v2 Complete generation mismatch: task_id=%s", task.task_id,
                    )
                    queue_metrics["owner_fencing_rejected"] += 1
            except Exception as e:
                logger.warning("v2 Complete error: task_id=%s error=%s", task.task_id, e)
    except asyncio.CancelledError:
        raise
    except FencingRejectedError:
        logger.warning(
            "v2 DB fencing rejected (stale worker): task_id=%s type=%s gen=%d",
            task.task_id, task.task_type, task.generation,
        )
        queue_metrics["owner_fencing_rejected"] += 1
        # Do NOT call fail_v2 — this worker no longer owns the fence
    except Exception as e:
        logger.exception(
            "v2 Task failed: task_id=%s type=%s", task.task_id, task.task_type,
        )
        if owner_lost.is_set():
            queue_metrics["owner_fencing_rejected"] += 1
        else:
            try:
                await task_queue.fail_v2(task, str(e)[:500])
            except Exception as fe:
                logger.warning("v2 Fail error: task_id=%s error=%s", task.task_id, fe)
    finally:
        cancel_watcher.cancel()
        try:
            await cancel_watcher
        except (asyncio.CancelledError, Exception):
            pass

        hb_task.cancel()
        try:
            await hb_task
        except (asyncio.CancelledError, Exception):
            pass

        if not process_task.done():
            process_task.cancel()
            try:
                await process_task
            except (asyncio.CancelledError, Exception):
                pass

        sem.release()


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

    semaphore = asyncio.Semaphore(settings.WORKER_CONCURRENCY)

    task_types = [
        TASK_TYPE_IMPORT_PIPELINE,
        TASK_TYPE_IMAGE_PIPELINE,
        TASK_TYPE_EXCEL_PIPELINE,
        TASK_TYPE_RESUME_PIPELINE,
        TASK_TYPE_ADMIN_RESUME,
        TASK_TYPE_BATCH_IMAGE,
        TASK_TYPE_FORMULA_BATCH,
    ]

    logger.info(
        "v2 Dispatcher started: concurrency=%d poll=%ss",
        settings.WORKER_CONCURRENCY, poll_interval,
    )

    _redis_failure_count = 0
    _max_redis_failures = 10

    try:
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
                _redis_failure_count += 1
                queue_metrics["queue_redis_failure"] += 1
                backoff = min(e.retry_after * (1 << min(_redis_failure_count - 1, 4)), 300)
                logger.error(
                    "v2 Dispatcher Redis unavailable (failure #%d): %s — backing off %ds",
                    _redis_failure_count, e, backoff,
                )
                if _redis_failure_count >= _max_redis_failures:
                    logger.critical(
                        "v2 Dispatcher circuit breaker OPEN after %d Redis failures — stopping claim loop",
                        _redis_failure_count,
                    )
                    break
                await asyncio.sleep(backoff)
                continue

            _redis_failure_count = 0

            if task is None:
                # No task available — release slot and sleep
                semaphore.release()
                await asyncio.sleep(poll_interval)
                continue

            # 3. Spawn background processing — task releases sem on completion
            proc_task = asyncio.create_task(
                _process_claimed_task_v2(task, lease_sec, semaphore),
                name=f"proc:{task.task_id}",
            )
            _v2_active_processing.add(proc_task)
            proc_task.add_done_callback(_v2_active_processing.discard)

            # Yield control briefly so the just-created task can start
            await asyncio.sleep(0)
    except asyncio.CancelledError:
        logger.info("v2 Dispatcher cancelled")
        raise
    finally:
        _v2_worker_running = False
        logger.info("v2 Dispatcher stopped")


async def _v2_heartbeat_loop_with_lease_window(
    task: Task, lease_sec: int, owner_lost: asyncio.Event | None = None,
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
        try:
            ok = await task_queue.heartbeat_v2(task, lease_sec=lease_sec)
            if ok == 1:
                # Check for cancel_requested flag on the task hash
                try:
                    task_data = await task_queue.get_task_v2(task.task_id)
                    if task_data and task_data.get("cancel_requested") == "1":
                        logger.warning(
                            "v2 Cancel requested, stopping: task_id=%s reason=%s",
                            task.task_id, task_data.get("cancel_reason", ""),
                        )
                        if owner_lost is not None:
                            owner_lost.set()
                        break
                except Exception:
                    pass  # Cancel check failure is non-fatal for heartbeat
                await asyncio.sleep(interval)
                continue

            # Explicit rejection from Lua — fencing failure
            logger.warning(
                "v2 Heartbeat rejected (code=%d), owner lost: task_id=%s",
                ok, task.task_id,
            )
            queue_metrics["lease_renewal_failure"] += 1
            if owner_lost is not None:
                owner_lost.set()
            break
        except (redis_exc.ConnectionError, redis_exc.TimeoutError) as exc:
            # Transient error — check lease window before giving up
            lease_window_remaining = task.lease_expires_at - time.time()
            if lease_window_remaining < interval * 2:
                logger.warning(
                    "v2 Heartbeat transient error + short lease window (%.1fs < %ds), "
                    "owner lost: task_id=%s error=%s",
                    lease_window_remaining, interval * 2, task.task_id, exc,
                )
                queue_metrics["lease_renewal_failure"] += 1
                if owner_lost is not None:
                    owner_lost.set()
                break

            # Safe window — retry once
            logger.warning(
                "v2 Heartbeat transient error, retrying once: task_id=%s error=%s",
                task.task_id, exc,
            )
            try:
                await asyncio.sleep(1)
                ok = await task_queue.heartbeat_v2(task, lease_sec=lease_sec)
                if ok == 1:
                    await asyncio.sleep(interval)
                    continue
            except Exception:
                pass

            logger.warning(
                "v2 Heartbeat retry failed, owner lost: task_id=%s", task.task_id,
            )
            queue_metrics["lease_renewal_failure"] += 1
            if owner_lost is not None:
                owner_lost.set()
            break
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning(
                "v2 Heartbeat unexpected error, owner lost: task_id=%s error=%s",
                task.task_id, exc,
            )
            queue_metrics["lease_renewal_failure"] += 1
            if owner_lost is not None:
                owner_lost.set()
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
    set_draining_v2()
    logger.info(
        "v2 Graceful shutdown: draining set, waiting up to %ds for %d active tasks",
        grace_sec, len(_v2_active_processing),
    )

    if not _v2_active_processing:
        stop_worker_v2()
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
    stop_worker_v2()


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


async def _heartbeat_loop(task: Task, lease_sec: int, owner_lost: asyncio.Event | None = None) -> None:
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

    types = task_types or [
        TASK_TYPE_IMPORT_PIPELINE,
        TASK_TYPE_IMAGE_PIPELINE,
        TASK_TYPE_EXCEL_PIPELINE,
        TASK_TYPE_RESUME_PIPELINE,
        TASK_TYPE_ADMIN_RESUME,
        TASK_TYPE_BATCH_IMAGE,
        TASK_TYPE_FORMULA_BATCH,
        TASK_TYPE_PREWARM_ANALYSIS,
    ]

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

    types = task_types or [
        TASK_TYPE_IMPORT_PIPELINE,
        TASK_TYPE_IMAGE_PIPELINE,
        TASK_TYPE_EXCEL_PIPELINE,
        TASK_TYPE_RESUME_PIPELINE,
        TASK_TYPE_ADMIN_RESUME,
        TASK_TYPE_BATCH_IMAGE,
        TASK_TYPE_FORMULA_BATCH,
        TASK_TYPE_PREWARM_ANALYSIS,
    ]

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
