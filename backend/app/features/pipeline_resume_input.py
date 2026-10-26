"""Resume pipeline input with historical session and live lookup boundaries."""

from __future__ import annotations

from app.features.pipeline_resume_state import ResumeRunState


async def load_resume_pipeline(state: ResumeRunState) -> bool:
    """Load the existing pipeline without acquiring independent sessions."""
    state.opts = (
        state.port("dict")(state.values["options"]) if state.values["options"] else {}
    )
    state.session_factory = state.port("_derive_session_factory")(state.values["db"])
    state.pipeline_row = (
        await state.values["db"].execute(
            state.values["select"](state.values["ImportPipelineRow"]).where(
                state.values["ImportPipelineRow"].pipeline_id
                == state.values["pipeline_id"]
            )
        )
    ).scalar_one_or_none()
    if state.pipeline_row is None:
        state.port("logger").warning(
            "resume_pipeline_background: pipeline %s missing, abort",
            state.values["pipeline_id"],
        )
        return False
    return True


async def recover_resume_subject(state: ResumeRunState) -> None:
    """Recover caller-omitted subject fields on a best-effort basis."""
    if state.values["subject_id"] is None:
        try:
            ckpt_data = await state.values["ckpt"].get_stage_checkpoint(
                state.values["pipeline_id"]
            )
            if ckpt_data:
                state.values["subject_id"] = ckpt_data.get("subject_id")
                if not state.values["subject"] and ckpt_data.get("subject"):
                    state.values["subject"] = ckpt_data["subject"]
        except state.port("Exception"):
            state.port("logger").debug(
                "resume: could not read checkpoint for subject_id recovery"
            )


async def load_resume_chunks(state: ResumeRunState) -> bool:
    """Keep pending order and derive metadata from the last ordered chunk."""
    state.pending = await state.values["ckpt"].get_pending_chunks(
        state.values["db"], state.values["pipeline_id"]
    )
    if not state.pending:
        await state.values["ckpt"].update_pipeline_status(
            state.values["db"],
            state.values["pipeline_id"],
            status="completed",
            finished=True,
        )
        await state.values["ckpt"].invalidate_progress_cache(
            state.values["pipeline_id"]
        )
        return False
    state.all_chunks = (
        (
            await state.values["db"].execute(
                state.values["select"](state.values["ImportPipelineChunk"])
                .where(
                    state.values["ImportPipelineChunk"].pipeline_id
                    == state.values["pipeline_id"]
                )
                .order_by(state.values["ImportPipelineChunk"].chunk_index)
            )
        )
        .scalars()
        .all()
    )
    if not state.all_chunks:
        state.port("logger").warning(
            "resume_pipeline_background: pipeline %s has no chunk rows",
            state.values["pipeline_id"],
        )
        return False
    state.total_pages = state.pipeline_row.total_pages or state.all_chunks[-1].page_end
    state.chunk_overlap = state.port("_resolve_chunk_overlap")()
    state.max_chunk_index = state.all_chunks[-1].chunk_index
    state.completed_batch_ids = [
        c.batch_id for c in state.all_chunks if c.status == "completed" and c.batch_id
    ]
    state.snapshot = state.pipeline_row.watermark_snapshot
    return True
