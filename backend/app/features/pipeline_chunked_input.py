"""Chunked pipeline input with historical live ports and session ownership."""

from __future__ import annotations

from app.features.pipeline_chunked_state import ChunkedRunState


def prepare_chunked_run(state: ChunkedRunState) -> None:
    """Resolve run configuration before acquiring any sessions."""
    state.shared = state.values["shared"]
    state.total_pages = state.values["chunk_ranges"][-1][1]
    state.chunk_size = state.port("_resolve_chunk_size")()
    state.chunk_overlap = state.port("_resolve_chunk_overlap")()
    state.session_factory = state.port("_derive_session_factory")(state.values["db"])
    state.watermark_snapshot = state.port("_serialize_watermark_patterns")(
        state.shared.get("watermark_patterns") or []
    )


async def initialize_chunked_checkpoints(state: ChunkedRunState) -> None:
    """Create parent and child checkpoint records in one short session."""
    async with state.session_factory() as init_db:
        await state.values["ckpt"].ensure_pipeline_record(
            init_db,
            pipeline_id=state.values["self"].pipeline_id,
            source_type=state.values["source_type"],
            source_file=state.values["source_file"] or None,
            total_pages=state.total_pages,
            chunk_size=state.chunk_size,
            created_by=state.values["self"].created_by,
            source_sha256=state.values["self"].source_sha256,
            watermark_snapshot=state.watermark_snapshot or None,
        )
        await state.values["ckpt"].ensure_chunk_records(
            init_db, state.values["self"].pipeline_id, state.values["chunk_ranges"]
        )


async def load_chunked_hash_index(state: ChunkedRunState) -> None:
    """Load one shared index, degrading only ordinary load-session failures."""
    state.hash_index = state.values["GlobalHashIndex"]()
    try:
        async with state.session_factory() as init_db:
            await state.hash_index.load(init_db)
    except state.port("Exception"):
        state.port("logger").exception(
            "GlobalHashIndex.load failed; chunked similarity match will fallback"
        )
        state.hash_index = None
    if state.hash_index is not None:
        state.shared = {**state.shared, "hash_index": state.hash_index}


def start_chunked_run(state: ChunkedRunState) -> None:
    """Create invocation-local dedup state and emit the start observation."""
    state.chunk_results = []
    state.pipeline_errors = []
    state.any_chunk_failed = False
    state.seen_hashes = state.port("set")()
    state._chunked_logger = state.port("logging").getLogger("app.pipeline")
    state._chunked_start = state.port("time").monotonic()
    state.port("log_event")(
        state._chunked_logger,
        "pipeline.chunked.start",
        pipeline_id=state.values["self"].pipeline_id,
        total_pages=state.total_pages,
        chunk_size=state.chunk_size,
        chunk_overlap=state.chunk_overlap,
        total_chunks=state.port("len")(state.values["chunk_ranges"]),
    )
