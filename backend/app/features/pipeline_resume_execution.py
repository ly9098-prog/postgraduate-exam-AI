"""Resume pipeline execution with historical session and live lookup boundaries."""

from __future__ import annotations

from app.features.pipeline_resume_state import ResumeRunState


async def start_resume_replay(state: ResumeRunState) -> None:
    """Publish running before constructing the replay pipeline and timestamp."""
    async with state.session_factory() as init_db:
        await state.values["ckpt"].update_pipeline_status(
            init_db, state.values["pipeline_id"], status="running"
        )
    await state.values["ckpt"].invalidate_progress_cache(state.values["pipeline_id"])
    state.pipeline = state.port("ImportPipeline")(options=state.opts)
    state.pipeline.pipeline_id = state.values["pipeline_id"]
    state.started_at = state.port("serialize_utc_datetime")(state.port("utcnow")())
    state.chunk_results = []
    state.any_chunk_failed = False


async def execute_resume_replay(state: ResumeRunState) -> None:
    """Rebuild seen hashes and replay with per-chunk sessions and loop-only cleanup."""
    async with state.session_factory() as init_db:
        seen_hashes = await state.port("_load_seen_hashes_for_resume")(
            init_db, state.values["pipeline_id"]
        )
    await start_resume_replay(state)
    try:
        for chunk in state.pending:
            async with state.session_factory() as chunk_db:
                outcome = await state.pipeline._execute_chunk(
                    chunk_index=chunk.chunk_index,
                    page_start=chunk.page_start,
                    logical_end=chunk.page_end,
                    total_pages=state.total_pages,
                    is_last_chunk=chunk.chunk_index == state.max_chunk_index,
                    chunk_overlap=state.chunk_overlap,
                    file_content=None,
                    file_path=state.values["file_path"],
                    source_type=state.pipeline_row.source_type or "pdf",
                    source_file=state.pipeline_row.source_file or "",
                    subject=state.values["subject"],
                    subject_id=state.values["subject_id"],
                    opts=state.opts,
                    db=chunk_db,
                    shared=state.shared,
                    progress_callback=None,
                    started_at=state.started_at,
                    seen_hashes=seen_hashes,
                    hash_index=state.hash_index,
                    page_image_refs=None,
                )
            state.chunk_results.append(outcome)
            if outcome["status"] == "failed":
                state.any_chunk_failed = True
    finally:
        if state.hash_index is not None:
            state.hash_index._question_index.clear()
            state.hash_index._import_index.clear()
