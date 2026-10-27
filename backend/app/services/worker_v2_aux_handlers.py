"""Invoke formula and batch-image handlers using invocation-owned work copies."""

from __future__ import annotations

from app.services.worker_v2_state import WorkerTaskState


async def run_formula_handler(state: WorkerTaskState) -> None:
    from sqlalchemy import select

    from app.core.database import async_session
    from app.models.formula import FormulaCard
    from app.services.formula_graph_batch_runner import process_batch

    card_ids = state.payload.get("card_ids", [])
    admin_id = state.payload.get("admin_id", 0)
    job_id = state.payload.get("job_id", "")
    async with async_session() as db:
        result = await db.execute(select(FormulaCard).where(FormulaCard.id.in_(card_ids)))
        cards = list(result.scalars().all())
    await process_batch(job_id, cards, admin_id)


async def run_batch_image_handler(state: WorkerTaskState) -> None:
    from app.features import batch_image_import_service as batch_svc

    job_id = state.payload.get("job_id", "")
    staging_ids: list[str] = state.payload.get("staging_object_ids", [])
    subject = state.payload.get("subject")
    subject_id = state.payload.get("subject_id")
    options = state.payload.get("options", {})
    concurrency = state.payload.get("concurrency", 2)
    if state.fence_record_id:
        await state.namespace["_verify_fencing_or_cancel"](
            state.task, state.fence_record_id, state.task_type
        )
    sources: list[batch_svc.BatchImageSource] = []
    for idx, staging_id in enumerate(staging_ids):
        if not staging_id:
            continue
        work_path = await state.resolve_owned_staging(staging_id)
        sources.append(
            batch_svc.BatchImageSource(
                seq=idx + 1, source_file=f"image_{idx + 1}.png", temp_path=work_path
            )
        )
    if not sources:
        raise FileNotFoundError(f"No valid staging sources for batch image job {job_id}")
    await batch_svc.run_batch_job(
        job_id=job_id,
        sources=sources,
        subject=subject,
        subject_id=subject_id,
        options=options,
        concurrency=concurrency,
    )
