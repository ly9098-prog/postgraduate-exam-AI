"""Chunked pipeline execution with historical live ports and session ownership."""

from __future__ import annotations

from app.features.pipeline_chunked_state import ChunkedRunState


async def execute_chunked_loop(state: ChunkedRunState) -> None:
    """Run each chunk in its own session and release index maps on loop exit."""
    try:
        for chunk_index, (page_start, logical_end) in state.port("enumerate")(
            state.values["chunk_ranges"]
        ):
            is_last_chunk = (
                chunk_index == state.port("len")(state.values["chunk_ranges"]) - 1
            )
            async with state.session_factory() as chunk_db:
                outcome = await state.values["self"]._execute_chunk(
                    chunk_index=chunk_index,
                    page_start=page_start,
                    logical_end=logical_end,
                    total_pages=state.total_pages,
                    is_last_chunk=is_last_chunk,
                    chunk_overlap=state.chunk_overlap,
                    file_content=state.values["file_content"],
                    file_path=state.values["file_path"],
                    source_type=state.values["source_type"],
                    source_file=state.values["source_file"],
                    subject=state.values["subject"],
                    subject_id=state.values["subject_id"],
                    opts=state.values["opts"],
                    db=chunk_db,
                    shared=state.shared,
                    progress_callback=state.values["progress_callback"],
                    started_at=state.values["started_at"],
                    seen_hashes=state.seen_hashes,
                    hash_index=state.hash_index,
                    page_images=state.values["page_images"],
                    page_image_refs=state.values["page_image_refs"],
                )
            state.chunk_results.append(outcome)
            if outcome["status"] == "failed":
                state.any_chunk_failed = True
                state.pipeline_errors.append(
                    f"chunk {chunk_index} (pages {page_start}-{logical_end}) failed: {outcome['error_message']}"
                )
    finally:
        if state.hash_index is not None:
            state.hash_index._question_index.clear()
            state.hash_index._import_index.clear()
