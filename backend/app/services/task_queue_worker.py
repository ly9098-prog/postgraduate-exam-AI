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

from app.services.staging_storage import async_lease_object, async_retrieve_file
from app.services.task_queue_service import EnqueueResult, Task, task_queue

logger = logging.getLogger("postgraduate-ai.task-worker")


async def _resolve_staging_path(staging_object_id: str) -> EnqueueResult:
    """Resolve a staging object ID to a local file path.

    Raises FileNotFoundError if the staging object does not exist.
    The returned path is read-only; the caller must not delete it.

    Automatically acquires a lease on the staging object to prevent
    cleanup from deleting it while the worker is processing the task.
    """
    if not staging_object_id:
        raise FileNotFoundError("staging_object_id is empty")
    staged_path = await async_retrieve_file(staging_object_id)
    if not staged_path:
        raise FileNotFoundError(f"Staging object {staging_object_id} not found")
    # Acquire lease to prevent cleanup during processing
    await async_lease_object(staging_object_id)
    return staged_path


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

# ── task type constants ──

TASK_TYPE_IMPORT_PIPELINE = "import_pipeline"
TASK_TYPE_RESUME_PIPELINE = "resume_pipeline"
TASK_TYPE_ADMIN_RESUME = "admin_resume"
TASK_TYPE_IMAGE_PIPELINE = "image_pipeline"
TASK_TYPE_EXCEL_PIPELINE = "excel_pipeline"
TASK_TYPE_PREWARM_ANALYSIS = "prewarm_analysis"
TASK_TYPE_FORMULA_BATCH = "formula_batch"
TASK_TYPE_BATCH_IMAGE = "batch_image"

# ── enqueue helpers ──

_LEASE_SEC = 600  # 10 minutes default lease


async def enqueue_import_pipeline(
    pipeline_id: str,
    file_path: str,
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
    return await task_queue.enqueue(
        TASK_TYPE_IMPORT_PIPELINE,
        payload,
        task_id=f"import:{pipeline_id}",
        max_retries=2,
    )


async def enqueue_resume_pipeline(
    pipeline_id: str,
    file_path: str,
    staging_object_id: str,
    subject: str | None,
    subject_id: int | None,
    options: dict,
) -> EnqueueResult:
    """Enqueue a pipeline resume task."""
    payload = {
        "pipeline_id": pipeline_id,
        "file_path": file_path,
        "staging_object_id": staging_object_id,
        "subject": subject,
        "subject_id": subject_id,
        "options": options,
    }
    return await task_queue.enqueue(
        TASK_TYPE_RESUME_PIPELINE,
        payload,
        task_id=f"resume:{pipeline_id}",
        max_retries=2,
    )


async def enqueue_image_pipeline(
    pipeline_id: str,
    image_path: str,
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
    return await task_queue.enqueue(
        TASK_TYPE_IMAGE_PIPELINE,
        payload,
        task_id=f"image:{pipeline_id}",
        max_retries=2,
    )


async def enqueue_excel_pipeline(
    pipeline_id: str,
    file_path: str,
    staging_object_id: str,
    source_file: str,
) -> EnqueueResult:
    """Enqueue an Excel import pipeline task."""
    payload = {
        "pipeline_id": pipeline_id,
        "source_file": source_file,
        "staging_object_id": staging_object_id,
    }
    return await task_queue.enqueue(
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
    return await task_queue.enqueue(
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
    return await task_queue.enqueue(
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
    return await task_queue.enqueue(
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
