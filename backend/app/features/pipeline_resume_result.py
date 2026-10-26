"""Resume pipeline result with historical session and live lookup boundaries."""

from __future__ import annotations

from app.features.pipeline_resume_state import ResumeRunState


async def finalize_resume(state: ResumeRunState) -> None:
    """Recompute persisted failures without cached progress before final invalidation."""
    async with state.session_factory() as final_db:
        progress = await state.values["ckpt"].get_pipeline_progress(
            final_db, state.values["pipeline_id"], use_cache=False
        )
        still_failing = progress and progress.get("failed_chunks", 0) > 0
        overall_status = (
            "paused" if state.any_chunk_failed or still_failing else "completed"
        )
        await state.values["ckpt"].update_pipeline_status(
            final_db,
            state.values["pipeline_id"],
            status=overall_status,
            finished=overall_status == "completed",
        )
    await state.values["ckpt"].invalidate_progress_cache(state.values["pipeline_id"])
