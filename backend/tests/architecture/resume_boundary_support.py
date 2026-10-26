"""Explicit resume-helper capabilities and preserved entrypoint contract."""

FUNCTIONS = {
    "state": {"port"},
    "input": {"load_resume_pipeline", "recover_resume_subject", "load_resume_chunks"},
    "context": {
        "resolve_resume_mode",
        "resolve_resume_watermarks",
        "load_resume_hash_index",
    },
    "execution": {"start_resume_replay", "execute_resume_replay"},
    "result": {"finalize_resume"},
}
PORTS = {
    "load_resume_pipeline": {"dict", "_derive_session_factory", "logger"},
    "recover_resume_subject": {"Exception", "logger"},
    "load_resume_chunks": {"logger", "_resolve_chunk_overlap"},
    "resolve_resume_mode": {"ImportMode", "ValueError", "get_strategy"},
    "resolve_resume_watermarks": {
        "_deserialize_watermark_patterns",
        "logger",
        "Exception",
    },
    "load_resume_hash_index": {"Exception", "logger"},
    "start_resume_replay": {"ImportPipeline", "serialize_utc_datetime", "utcnow"},
    "execute_resume_replay": {"_load_seen_hashes_for_resume"},
    "finalize_resume": set(),
}
VALUES = {
    "load_resume_pipeline": {
        "options",
        "db",
        "select",
        "ImportPipelineRow",
        "pipeline_id",
    },
    "recover_resume_subject": {"subject_id", "subject", "ckpt", "pipeline_id"},
    "load_resume_chunks": {
        "ckpt",
        "db",
        "pipeline_id",
        "select",
        "ImportPipelineChunk",
    },
    "resolve_resume_mode": set(),
    "resolve_resume_watermarks": {"pipeline_id", "db"},
    "load_resume_hash_index": {"GlobalHashIndex"},
    "start_resume_replay": {"ckpt", "pipeline_id"},
    "execute_resume_replay": {"pipeline_id", "file_path", "subject", "subject_id"},
    "finalize_resume": {"ckpt", "pipeline_id"},
}
ENTRY = '''
async def resume_pipeline_background(
    *, pipeline_id: str, file_path: str, subject: str | None = None,
    subject_id: int | None = None, options: dict | None = None, db,
) -> None:
    """Entry documentation."""
    from sqlalchemy import select
    from app.features import pipeline_checkpoint as ckpt
    from app.features.global_hash_index import GlobalHashIndex
    from app.models.import_pipeline import ImportPipeline as ImportPipelineRow
    from app.models.import_pipeline import ImportPipelineChunk
    state = ResumeRunState(locals(), globals())
    if not await load_resume_pipeline(state):
        return
    await recover_resume_subject(state)
    if not await load_resume_chunks(state):
        return
    resolve_resume_mode(state)
    await resolve_resume_watermarks(state)
    await load_resume_hash_index(state)
    await execute_resume_replay(state)
    await finalize_resume(state)
'''


STATE_FIELDS = {
    "load_resume_pipeline": {"opts", "session_factory", "pipeline_row"},
    "recover_resume_subject": set(),
    "load_resume_chunks": {
        "pending",
        "all_chunks",
        "pipeline_row",
        "total_pages",
        "chunk_overlap",
        "max_chunk_index",
        "completed_batch_ids",
        "snapshot",
    },
    "resolve_resume_mode": {"mode_str", "opts", "import_mode", "strategy"},
    "resolve_resume_watermarks": {
        "watermark_patterns",
        "snapshot",
        "shared",
        "import_mode",
        "strategy",
    },
    "load_resume_hash_index": {
        "hash_index",
        "session_factory",
        "completed_batch_ids",
        "shared",
    },
    "start_resume_replay": {
        "session_factory",
        "pipeline",
        "started_at",
        "chunk_results",
        "any_chunk_failed",
        "opts",
    },
    "execute_resume_replay": {
        "session_factory",
        "pending",
        "pipeline",
        "total_pages",
        "max_chunk_index",
        "chunk_overlap",
        "pipeline_row",
        "opts",
        "shared",
        "started_at",
        "hash_index",
        "chunk_results",
        "any_chunk_failed",
    },
    "finalize_resume": {"session_factory", "any_chunk_failed"},
}
