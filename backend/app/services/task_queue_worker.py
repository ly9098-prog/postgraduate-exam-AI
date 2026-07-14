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
import json
import logging
import time
import uuid
from typing import Any, Callable

from app.core.config import settings
from app.services.task_queue_service import Task, task_queue

logger = logging.getLogger("postgraduate-ai.task-worker")

# ── task type constants ──

TASK_TYPE_IMPORT_PIPELINE = "import_pipeline"
TASK_TYPE_RESUME_PIPELINE = "resume_pipeline"
TASK_TYPE_IMAGE_PIPELINE = "image_pipeline"
TASK_TYPE_EXCEL_PIPELINE = "excel_pipeline"
TASK_TYPE_PREWARM_ANALYSIS = "prewarm_analysis"
TASK_TYPE_FORMULA_BATCH = "formula_batch"

# ── enqueue helpers ──

_LEASE_SEC = 600  # 10 minutes default lease


async def enqueue_import_pipeline(
    pipeline_id: str,
    file_content: bytes,
    source_type: str,
    source_file: str,
    subject: str | None,
    subject_id: int | None,
    options: dict,
    created_by: str | None = None,
) -> str:
    """Enqueue an import pipeline task via the durable queue."""
    # Store file content info in payload (actual bytes go to file store)
    # For now, the pipeline store (in-memory or Redis) holds the execution state
    payload = {
        "pipeline_id": pipeline_id,
        "source_type": source_type,
        "source_file": source_file,
        "subject": subject,
        "subject_id": subject_id,
        "options": options,
        "created_by": created_by,
        # The pipeline store keeps file_content in memory for now.
        # TODO: migrate to shared file storage for multi-worker support.
        "_has_file_content": True,
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
    subject: str | None,
    subject_id: int | None,
    options: dict,
) -> str:
    """Enqueue a pipeline resume task."""
    payload = {
        "pipeline_id": pipeline_id,
        "file_path": file_path,
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
    image_content: bytes,
    source_file: str,
    subject: str | None,
    subject_id: int | None,
    options: dict,
) -> str:
    """Enqueue an image OCR pipeline task."""
    payload = {
        "pipeline_id": pipeline_id,
        "source_file": source_file,
        "subject": subject,
        "subject_id": subject_id,
        "options": options,
        "_has_file_content": True,
    }
    return await task_queue.enqueue(
        TASK_TYPE_IMAGE_PIPELINE,
        payload,
        task_id=f"image:{pipeline_id}",
        max_retries=2,
    )


async def enqueue_excel_pipeline(
    pipeline_id: str,
    file_content: bytes,
    source_file: str,
) -> str:
    """Enqueue an Excel import pipeline task."""
    payload = {
        "pipeline_id": pipeline_id,
        "source_file": source_file,
        "_has_file_content": True,
    }
    return await task_queue.enqueue(
        TASK_TYPE_EXCEL_PIPELINE,
        payload,
        task_id=f"excel:{pipeline_id}",
        max_retries=2,
    )


# ── worker runner ──

_worker_running = False
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

        # Reconstruct file_content from pipeline store
        from app.services.import_pipeline_service import _get_pipeline_store

        store = await _get_pipeline_store(pipeline_id)
        file_content = (store or {}).get("_file_content")
        await _run_pipeline_with_db(
            pipeline_id=pipeline_id,
            file_content=file_content,
            source_type=payload.get("source_type", "pdf"),
            source_file=payload.get("source_file", ""),
            subject=payload.get("subject"),
            subject_id=payload.get("subject_id"),
            options=payload.get("options", {}),
            created_by=payload.get("created_by"),
        )

    elif task_type == TASK_TYPE_IMAGE_PIPELINE:
        from app.services.import_pipeline_service import _run_image_pipeline_with_db

        store = await _get_pipeline_store(pipeline_id)
        image_content = (store or {}).get("_file_content")
        await _run_image_pipeline_with_db(
            pipeline_id=pipeline_id,
            image_content=image_content,
            source_file=payload.get("source_file", ""),
            subject=payload.get("subject"),
            subject_id=payload.get("subject_id"),
            options=payload.get("options", {}),
        )

    elif task_type == TASK_TYPE_EXCEL_PIPELINE:
        from app.services.import_pipeline_service import _run_excel_pipeline_with_db

        store = await _get_pipeline_store(pipeline_id)
        file_content = (store or {}).get("_file_content")
        from app.features import question_pipeline as pipeline_svc

        await _run_excel_pipeline_with_db(
            pipeline_id=pipeline_id,
            file_content=file_content,
            source_file=payload.get("source_file", ""),
            import_excel_fn=pipeline_svc.import_excel,
        )

    elif task_type == TASK_TYPE_RESUME_PIPELINE:
        # Resume — the calling code handles execution inline for now
        logger.warning(
            "Resume pipeline via worker not yet fully implemented: %s",
            pipeline_id,
        )

    else:
        logger.warning("Unknown task type: %s", task_type)


async def run_pipeline_worker(
    poll_interval: float = 1.0,
    lease_sec: int = _LEASE_SEC,
) -> None:
    """Run the import pipeline worker loop.

    Dequeues tasks, processes them with heartbeat, and handles
    completion/failure with retries.
    """
    global _worker_running
    _worker_running = True

    task_types = [
        TASK_TYPE_IMPORT_PIPELINE,
        TASK_TYPE_IMAGE_PIPELINE,
        TASK_TYPE_EXCEL_PIPELINE,
    ]

    logger.info("Pipeline worker started: polling every %ss", poll_interval)

    while _worker_running:
        processed = False
        for task_type in task_types:
            try:
                task = await task_queue.dequeue(task_type, lease_sec=lease_sec)
            except Exception as e:
                logger.warning("Dequeue failed for %s: %s", task_type, e)
                continue

            if task is None:
                continue

            processed = True
            heartbeat_task = asyncio.create_task(
                _heartbeat_loop(task, lease_sec)
            )

            try:
                await _process_task(task)
                await task_queue.complete(task)
                logger.info(
                    "Task completed successfully: task_id=%s", task.task_id
                )
            except Exception as e:
                logger.exception(
                    "Task failed: task_id=%s type=%s", task.task_id, task_type
                )
                await task_queue.fail(task, str(e))
            finally:
                heartbeat_task.cancel()

        if not processed:
            await asyncio.sleep(poll_interval)


async def _heartbeat_loop(task: Task, lease_sec: int) -> None:
    """Periodically extend task lease while worker is alive."""
    interval = max(lease_sec // 3, 10)
    while _worker_running:
        try:
            await task_queue.heartbeat(task, lease_sec)
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            break
        except Exception:
            break


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
    """Run the reaper loop: reclaim expired leases."""
    global _reaper_running
    _reaper_running = True

    types = task_types or [
        TASK_TYPE_IMPORT_PIPELINE,
        TASK_TYPE_IMAGE_PIPELINE,
        TASK_TYPE_EXCEL_PIPELINE,
        TASK_TYPE_RESUME_PIPELINE,
    ]

    while _reaper_running:
        try:
            await task_queue.run_reaper(types)
        except Exception as e:
            logger.warning("Reaper cycle failed: %s", e)
        await asyncio.sleep(interval)


async def stop_reaper() -> None:
    """Signal the reaper loop to stop."""
    global _reaper_running
    _reaper_running = False
