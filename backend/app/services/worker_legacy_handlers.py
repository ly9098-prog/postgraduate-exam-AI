"""Legacy task-queue worker handlers, kept lazy and provider-owned."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class LegacyTaskContext:
    task: Any
    payload: dict
    pipeline_id: str
    resolve_staging: Callable[[str], Awaitable[str]]
    namespace: dict[str, Any]


def _logger(context: LegacyTaskContext):
    return context.namespace["logger"]


async def handle_import_pipeline(context: LegacyTaskContext) -> None:
    from app.services.import_pipeline_service import _run_pipeline_with_db

    payload = context.payload
    staging_id = payload.get("staging_object_id", "")
    file_path = await context.resolve_staging(staging_id)
    await _run_pipeline_with_db(
        pipeline_id=context.pipeline_id,
        file_path=file_path,
        source_type=payload.get("source_type", "pdf"),
        source_file=payload.get("source_file", ""),
        subject=payload.get("subject"),
        subject_id=payload.get("subject_id"),
        options=payload.get("options", {}),
        created_by=payload.get("created_by"),
        source_sha256=payload.get("source_sha256"),
    )


async def handle_image_pipeline(context: LegacyTaskContext) -> None:
    from app.services.import_pipeline_service import _run_image_pipeline_with_db

    payload = context.payload
    staging_id = payload.get("staging_object_id", "")
    image_path = await context.resolve_staging(staging_id)
    if not image_path:
        raise FileNotFoundError(
            f"Staging object {staging_id} not found for image pipeline"
        )
    await _run_image_pipeline_with_db(
        pipeline_id=context.pipeline_id,
        image_path=image_path,
        source_file=payload.get("source_file", ""),
        subject=payload.get("subject"),
        subject_id=payload.get("subject_id"),
        options=payload.get("options", {}),
        created_by=payload.get("created_by"),
    )


async def handle_excel_pipeline(context: LegacyTaskContext) -> None:
    from app.features.pipeline_orchestrator import run_excel_pipeline_background

    payload = context.payload
    staging_id = payload.get("staging_object_id", "")
    file_path = await context.resolve_staging(staging_id)
    file_content = b""
    if file_path:
        open_file = context.namespace.get("open", open)
        with open_file(file_path, "rb") as file_handle:
            file_content = file_handle.read()
    from app.features import question_import_writer as pipeline_svc

    await run_excel_pipeline_background(
        pipeline_id=context.pipeline_id,
        file_content=file_content,
        source_file=payload.get("source_file", ""),
        import_excel_fn=pipeline_svc.import_excel,
        created_by=payload.get("created_by"),
    )


async def handle_resume_pipeline(context: LegacyTaskContext) -> None:
    from app.services.import_pipeline_service import run_resume_background

    payload = context.payload
    staging_id = payload.get("staging_object_id", "")
    file_path = await context.resolve_staging(staging_id)
    await run_resume_background(
        pipeline_id=context.pipeline_id,
        file_path=file_path,
        subject=payload.get("subject"),
        subject_id=payload.get("subject_id"),
        options=payload.get("options", {}),
    )


async def handle_admin_resume(context: LegacyTaskContext) -> None:
    from app.core.database import async_session
    from app.features.pipeline_coordinator_entry import run_pipeline
    from app.features.pipeline_orchestrator import (
        _get_stage_checkpoint,
        _set_pipeline_store,
    )

    payload = context.payload
    staging_id = payload.get("staging_object_id", "")
    file_path = await context.resolve_staging(staging_id)
    source_type = payload.get("source_type", "pdf")
    source_file = payload.get("source_file", "")
    subject = payload.get("subject")
    subject_id = payload.get("subject_id")
    options = payload.get("options", {})

    # Re-read checkpoint from shared Redis (cross-process accessible)
    checkpoint = await _get_stage_checkpoint(context.pipeline_id)
    async with async_session() as resume_db:
        result = await run_pipeline(
            file_path=file_path,
            source_type=source_type,
            source_file=source_file,
            subject=subject,
            subject_id=subject_id,
            options=options,
            db=resume_db,
            pipeline_id=context.pipeline_id,
            resume_from_checkpoint=checkpoint,
        )
    try:
        await _set_pipeline_store(context.pipeline_id, result)
    except Exception:
        _logger(context).warning(
            "Failed to store admin resume result for %s", context.pipeline_id
        )


async def handle_answer_projection(context: LegacyTaskContext) -> None:
    await context.namespace["_process_answer_projection_task"](context.task)


async def handle_error_diagnosis(context: LegacyTaskContext) -> None:
    await context.namespace["_process_error_diagnosis_task"](context.task)


async def handle_formula_batch(context: LegacyTaskContext) -> None:
    from sqlalchemy import select

    from app.core.database import async_session
    from app.models.formula import FormulaCard
    from app.services.formula_graph_batch_runner import process_batch

    payload = context.payload
    card_ids = payload.get("card_ids", [])
    admin_id = payload.get("admin_id", 0)
    job_id = payload.get("job_id", "")
    async with async_session() as db:
        result = await db.execute(
            select(FormulaCard).where(FormulaCard.id.in_(card_ids))
        )
        cards = list(result.scalars().all())
    await process_batch(job_id, cards, admin_id)


async def handle_batch_image(context: LegacyTaskContext) -> None:
    from app.features import batch_image_import_service as batch_svc

    payload = context.payload
    job_id = payload.get("job_id", "")
    staging_ids: list[str] = payload.get("staging_object_ids", [])
    subject = payload.get("subject")
    subject_id = payload.get("subject_id")
    options = payload.get("options", {})
    concurrency = payload.get("concurrency", 2)
    sources: list[batch_svc.BatchImageSource] = []
    for index, staging_id in enumerate(staging_ids):
        if not staging_id:
            _logger(context).warning(
                "Empty staging_object_id for batch image seq=%d job=%s",
                index + 1,
                job_id,
            )
            continue
        work_path = await context.resolve_staging(staging_id)
        sources.append(
            batch_svc.BatchImageSource(
                seq=index + 1,
                source_file=f"image_{index + 1}.png",
                temp_path=work_path,
            )
        )
    if not sources:
        raise FileNotFoundError(
            f"No valid staging sources for batch image job {job_id}"
        )
    await batch_svc.run_batch_job(
        job_id=job_id,
        sources=sources,
        subject=subject,
        subject_id=subject_id,
        options=options,
        concurrency=concurrency,
    )


def select_legacy_handler(
    task_type: str, namespace: dict[str, Any]
) -> Callable[[LegacyTaskContext], Awaitable[None]]:
    if task_type == namespace["TASK_TYPE_IMPORT_PIPELINE"]:
        return handle_import_pipeline
    if task_type == namespace["TASK_TYPE_IMAGE_PIPELINE"]:
        return handle_image_pipeline
    if task_type == namespace["TASK_TYPE_EXCEL_PIPELINE"]:
        return handle_excel_pipeline
    if task_type == namespace["TASK_TYPE_RESUME_PIPELINE"]:
        return handle_resume_pipeline
    if task_type == namespace["TASK_TYPE_ADMIN_RESUME"]:
        return handle_admin_resume
    if task_type == namespace["TASK_TYPE_ANSWER_PROJECTION"]:
        return handle_answer_projection
    if task_type == namespace["TASK_TYPE_ERROR_DIAGNOSIS"]:
        return handle_error_diagnosis
    if task_type == namespace["TASK_TYPE_FORMULA_BATCH"]:
        return handle_formula_batch
    if task_type == namespace["TASK_TYPE_BATCH_IMAGE"]:
        return handle_batch_image
    raise ValueError(f"unknown_task_type: {task_type}")
