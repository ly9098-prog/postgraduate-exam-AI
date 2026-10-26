"""Chunked pipeline result with historical live ports and session ownership."""

from __future__ import annotations

from app.features.pipeline_chunked_state import ChunkedRunState


async def finalize_chunked_checkpoint(state: ChunkedRunState) -> None:
    """Write the aggregate status before invalidating cached progress."""
    state.overall_status = "paused" if state.any_chunk_failed else "completed"
    async with state.session_factory() as final_db:
        await state.values["ckpt"].update_pipeline_status(
            final_db,
            state.values["self"].pipeline_id,
            status=state.overall_status,
            error_message=state.pipeline_errors[0] if state.pipeline_errors else None,
            finished=True,
        )
    await state.values["ckpt"].invalidate_progress_cache(
        state.values["self"].pipeline_id
    )


def aggregate_chunked_result(state: ChunkedRunState) -> None:
    """Aggregate live chunk results after the final checkpoint succeeds."""
    state.agg_stats = {
        "total_chunks": state.port("len")(state.values["chunk_ranges"]),
        "completed_chunks": state.port("sum")(
            (1 for c in state.chunk_results if c["status"] == "completed")
        ),
        "failed_chunks": state.port("sum")(
            (1 for c in state.chunk_results if c["status"] == "failed")
        ),
        "to_review": state.port("sum")(
            (c["question_count"] or 0 for c in state.chunk_results)
        ),
        "extracted": state.total_pages,
        "total": state.total_pages,
    }
    state.risk_flag_counts = state.port("_merge_risk_flag_counts")(state.chunk_results)
    state.finished_at = state.port("serialize_utc_datetime")(state.port("utcnow")())
    state.first_batch_id = state.port("next")(
        (c["batch_id"] for c in state.chunk_results if c["batch_id"]), ""
    )


def log_chunked_result(state: ChunkedRunState) -> None:
    """Observe completion after aggregate timestamps and batch selection."""
    _chunked_event = (
        "pipeline.chunked.finish"
        if state.overall_status == "completed"
        else "pipeline.chunked.paused"
    )
    _chunked_level = "info" if state.overall_status == "completed" else "warning"
    state.port("log_event")(
        state._chunked_logger,
        _chunked_event,
        level=_chunked_level,
        pipeline_id=state.values["self"].pipeline_id,
        total_pages=state.total_pages,
        chunk_size=state.chunk_size,
        chunk_overlap=state.chunk_overlap,
        total_chunks=state.port("len")(state.values["chunk_ranges"]),
        completed_chunks=state.agg_stats["completed_chunks"],
        failed_chunks=state.agg_stats["failed_chunks"],
        status=state.overall_status,
        duration_ms=state.port("round")(
            (state.port("time").monotonic() - state._chunked_start) * 1000
        ),
    )


def project_chunked_result(state: ChunkedRunState) -> dict:
    """Publish live aggregate references and a shallow index-stat snapshot."""
    return {
        "pipeline_id": state.values["self"].pipeline_id,
        "status": state.overall_status,
        "batch_id": state.first_batch_id,
        "stats": state.agg_stats,
        "diagnostics": {
            "chunked": True,
            "chunk_size": state.chunk_size,
            "chunk_overlap": state.chunk_overlap,
            "total_pages": state.total_pages,
            "risk_flag_counts": state.risk_flag_counts,
            "chunks": state.chunk_results,
            "hash_index": state.port("dict")(state.hash_index.stats)
            if state.hash_index is not None
            else None,
        },
        "stages": {},
        "errors": state.pipeline_errors,
        "started_at": state.values["started_at"],
        "finished_at": state.finished_at,
    }
