"""Invoke pipeline handlers with their original branch-local imports and ordering."""

from __future__ import annotations

from app.services.worker_v2_state import WorkerTaskState


async def run_import_handler(state: WorkerTaskState) -> None:
    from app.services.import_pipeline_service import _run_pipeline_with_db

    if state.fence_record_id:
        await state.namespace["_verify_fencing_or_cancel"](
            state.task, state.fence_record_id, state.task_type
        )
    staging_id = state.payload.get("staging_object_id", "")
    file_path = await state.resolve_owned_staging(staging_id)
    await _run_pipeline_with_db(
        pipeline_id=state.pipeline_id,
        file_path=file_path,
        source_type=state.payload.get("source_type", "pdf"),
        source_file=state.payload.get("source_file", ""),
        subject=state.payload.get("subject"),
        subject_id=state.payload.get("subject_id"),
        options=state.payload.get("options", {}),
        created_by=state.payload.get("created_by"),
        source_sha256=state.payload.get("source_sha256"),
    )


async def run_image_handler(state: WorkerTaskState) -> None:
    from app.services.import_pipeline_service import _run_image_pipeline_with_db

    staging_id = state.payload.get("staging_object_id", "")
    image_path = await state.resolve_owned_staging(staging_id)
    if not image_path:
        raise FileNotFoundError(f"Staging object {staging_id} not found for image pipeline")
    if state.fence_record_id:
        await state.namespace["_verify_fencing_or_cancel"](
            state.task, state.fence_record_id, state.task_type
        )
    await _run_image_pipeline_with_db(
        pipeline_id=state.pipeline_id,
        image_path=image_path,
        source_file=state.payload.get("source_file", ""),
        subject=state.payload.get("subject"),
        subject_id=state.payload.get("subject_id"),
        options=state.payload.get("options", {}),
        created_by=state.payload.get("created_by"),
    )


async def run_excel_handler(state: WorkerTaskState) -> None:
    from app.features.pipeline_orchestrator import run_excel_pipeline_background

    staging_id = state.payload.get("staging_object_id", "")
    file_path = await state.resolve_owned_staging(staging_id)
    file_content = b""
    if file_path:
        with state.lookup("open")(file_path, "rb") as _fh:
            file_content = _fh.read()
    from app.features import question_import_writer as pipeline_svc

    if state.fence_record_id:
        await state.namespace["_verify_fencing_or_cancel"](
            state.task, state.fence_record_id, state.task_type
        )
    await run_excel_pipeline_background(
        pipeline_id=state.pipeline_id,
        file_content=file_content,
        source_file=state.payload.get("source_file", ""),
        import_excel_fn=pipeline_svc.import_excel,
        created_by=state.payload.get("created_by"),
    )


async def run_resume_handler(state: WorkerTaskState) -> None:
    from app.services.import_pipeline_service import run_resume_background

    staging_id = state.payload.get("staging_object_id", "")
    file_path = await state.resolve_owned_staging(staging_id)
    if state.fence_record_id:
        await state.namespace["_verify_fencing_or_cancel"](
            state.task, state.fence_record_id, state.task_type
        )
    await run_resume_background(
        pipeline_id=state.pipeline_id,
        file_path=file_path,
        subject=state.payload.get("subject"),
        subject_id=state.payload.get("subject_id"),
        options=state.payload.get("options", {}),
    )


async def run_admin_resume_handler(state: WorkerTaskState) -> None:
    from app.core.database import async_session
    from app.features.pipeline_coordinator_entry import run_pipeline
    from app.features.pipeline_orchestrator import (
        _get_stage_checkpoint,
        _set_pipeline_store,
    )

    staging_id = state.payload.get("staging_object_id", "")
    file_path = await state.resolve_owned_staging(staging_id)
    source_type = state.payload.get("source_type", "pdf")
    source_file = state.payload.get("source_file", "")
    subject = state.payload.get("subject")
    subject_id = state.payload.get("subject_id")
    opts = state.payload.get("options", {})
    ckpt = await _get_stage_checkpoint(state.pipeline_id)
    if state.fence_record_id:
        await state.namespace["_verify_fencing_or_cancel"](
            state.task, state.fence_record_id, state.task_type
        )
    async with async_session() as resume_db:
        result = await run_pipeline(
            file_path=file_path,
            source_type=source_type,
            source_file=source_file,
            subject=subject,
            subject_id=subject_id,
            options=opts,
            db=resume_db,
            pipeline_id=state.pipeline_id,
            resume_from_checkpoint=ckpt,
        )
    try:
        await _set_pipeline_store(state.pipeline_id, result)
    except Exception:
        state.namespace["logger"].warning(
            "Failed to store admin resume result for %s", state.pipeline_id
        )
