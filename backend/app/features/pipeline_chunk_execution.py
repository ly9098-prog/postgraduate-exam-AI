"""Single-chunk execution with live runtime-port resolution and bounded stages."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChunkExecutionState:
    """Invocation-local state for one chunk; ports stay on the original caller."""

    pipeline: Any
    chunk_index: int
    page_start: int
    logical_end: int
    total_pages: int
    is_last_chunk: bool
    chunk_overlap: int
    file_content: Any
    file_path: Any
    source_type: str
    source_file: str
    subject: Any
    subject_id: Any
    opts: dict
    db: Any
    shared: dict
    progress_callback: Any
    started_at: Any
    seen_hashes: set
    hash_index: Any
    page_images: Any
    page_image_refs: Any
    namespace: dict
    checkpoint: Any = None
    chunk_logger: Any = None
    chunk_start: Any = 0
    effective_end: int = 0
    chunk_status: str = "completed"
    chunk_error: str | None = None
    chunk_result: dict = field(default_factory=dict)


def resolve_chunk_port(namespace: dict, name: str) -> Any:
    """Resolve the original global or builtin at each expression site."""
    if name in namespace:
        return namespace[name]
    builtins = namespace.get("__builtins__", globals().get("__builtins__"))
    if not isinstance(builtins, dict):
        builtins = vars(builtins)
    if name in builtins:
        return builtins[name]
    raise NameError(f"name '{name}' is not defined", name=name)


def build_chunk_execution_state(
    pipeline: Any, values: dict, namespace: dict
) -> ChunkExecutionState:
    """Capture call arguments and the original module namespace."""
    return ChunkExecutionState(
        pipeline=pipeline,
        chunk_index=values["chunk_index"],
        page_start=values["page_start"],
        logical_end=values["logical_end"],
        total_pages=values["total_pages"],
        is_last_chunk=values["is_last_chunk"],
        chunk_overlap=values["chunk_overlap"],
        file_content=values["file_content"],
        file_path=values["file_path"],
        source_type=values["source_type"],
        source_file=values["source_file"],
        subject=values["subject"],
        subject_id=values["subject_id"],
        opts=values["opts"],
        db=values["db"],
        shared=values["shared"],
        progress_callback=values["progress_callback"],
        started_at=values["started_at"],
        seen_hashes=values["seen_hashes"],
        hash_index=values["hash_index"],
        page_images=values["page_images"],
        page_image_refs=values["page_image_refs"],
        namespace=namespace,
    )


async def run_chunk_execution(state: ChunkExecutionState) -> dict:
    """Run the original chunk sequence without changing its failure boundary."""
    await render_chunk_page_window(state)
    await initialize_chunk_execution(state)
    state.effective_end = (
        state.logical_end
        if state.is_last_chunk
        else resolve_chunk_port(state.namespace, "min")(
            state.logical_end + state.chunk_overlap, state.total_pages
        )
    )
    await run_chunk_single_pass(state)
    await finalize_chunk_execution(state)
    return project_chunk_result(state)


async def render_chunk_page_window(state: ChunkExecutionState) -> None:
    """Render only this chunk's PDF window when the feature is enabled."""
    from app.core.config import settings
    from app.services.pdf_renderer_service import pdf_renderer

    if (
        settings.PDF_RENDER_PAGE_WINDOW <= 0
        or state.source_type != "pdf"
        or state.page_images is not None
    ):
        return

    chunk_page_images: dict[int, bytes] = {}
    async for page in pdf_renderer.iter_pages(
        file_content=state.file_content,
        file_path=state.file_path,
        source_type=state.source_type,
        page_start=state.page_start,
        page_end=state.logical_end,
    ):
        chunk_page_images[page.page_number] = page.png_bytes
        await page.aclose()
    if chunk_page_images:
        state.page_images = chunk_page_images


async def initialize_chunk_execution(state: ChunkExecutionState) -> None:
    """Mark the chunk running, invalidate progress, and emit the start event."""
    from app.features import pipeline_checkpoint as ckpt

    state.checkpoint = ckpt
    await ckpt.mark_chunk_running(
        state.db, state.pipeline.pipeline_id, state.chunk_index
    )
    await ckpt.invalidate_progress_cache(state.pipeline.pipeline_id)
    state.chunk_logger = resolve_chunk_port(state.namespace, "logging").getLogger(
        "app.pipeline"
    )
    state.chunk_start = resolve_chunk_port(state.namespace, "time").monotonic()
    resolve_chunk_port(state.namespace, "bind_log_context")(
        chunk_index=state.chunk_index
    )
    resolve_chunk_port(state.namespace, "log_event")(
        state.chunk_logger,
        "pipeline.chunk.start",
        pipeline_id=state.pipeline.pipeline_id,
        chunk_index=state.chunk_index,
        page_start=state.page_start,
        page_end=state.logical_end,
    )


async def run_chunk_single_pass(state: ChunkExecutionState) -> None:
    """Run one pass and isolate ordinary failures while preserving cancellation."""
    try:
        state.chunk_result = await state.pipeline._run_single_pass(
            file_content=state.file_content,
            file_path=state.file_path,
            source_type=state.source_type,
            source_file=state.source_file,
            subject=state.subject,
            subject_id=state.subject_id,
            opts=state.opts,
            db=state.db,
            shared=state.shared,
            progress_callback=state.progress_callback,
            started_at=state.started_at,
            page_start=state.page_start,
            page_end=state.effective_end,
            chunk_seen_hashes=state.seen_hashes,
            chunk_logical_end=state.logical_end,
            page_images=state.page_images,
            page_image_refs=state.page_image_refs,
        )
        if state.chunk_result.get("status") != "completed":
            state.chunk_status = "failed"
            errors = state.chunk_result.get("errors") or []
            state.chunk_error = (
                errors[0] if errors else "chunk failed without explicit error"
            )
    except resolve_chunk_port(state.namespace, "Exception") as exc:
        # A stage should normally isolate its own failures; this is the last
        # barrier for extract crashes and other pre-stage exceptions.
        resolve_chunk_port(state.namespace, "logger").exception(
            "chunk %d (pages %d-%d) raised unexpectedly",
            state.chunk_index,
            state.page_start,
            state.logical_end,
        )
        state.chunk_status = "failed"
        state.chunk_error = (
            f"{resolve_chunk_port(state.namespace, 'type')(exc).__name__}: {exc}"
        )
        state.chunk_result = {"errors": [state.chunk_error]}


async def finalize_chunk_execution(state: ChunkExecutionState) -> None:
    """Publish hashes, persist the terminal chunk state, and emit the result."""
    written = (state.chunk_result.get("stats") or {}).get("to_review", 0)
    batch_id = state.chunk_result.get("batch_id") or None
    if state.hash_index is not None and state.chunk_status == "completed":
        for subj, qhash, iid in state.chunk_result.get("review_new_hashes") or []:
            state.hash_index.add_import(subj, qhash, iid)

    await state.checkpoint.update_chunk_status(
        state.db,
        state.pipeline.pipeline_id,
        state.chunk_index,
        status=state.chunk_status,
        batch_id=batch_id,
        question_count=written,
        error_message=state.chunk_error,
    )
    await state.checkpoint.invalidate_progress_cache(state.pipeline.pipeline_id)

    event = (
        "pipeline.chunk.finish"
        if state.chunk_status == "completed"
        else "pipeline.chunk.error"
    )
    level = "info" if state.chunk_status == "completed" else "error"
    resolve_chunk_port(state.namespace, "log_event")(
        state.chunk_logger,
        event,
        level=level,
        pipeline_id=state.pipeline.pipeline_id,
        chunk_index=state.chunk_index,
        page_start=state.page_start,
        page_end=state.logical_end,
        effective_page_end=state.effective_end,
        status=state.chunk_status,
        duration_ms=resolve_chunk_port(state.namespace, "round")(
            (
                resolve_chunk_port(state.namespace, "time").monotonic()
                - state.chunk_start
            )
            * 1000
        ),
        batch_id=batch_id or "-",
        question_count=written,
        error_message=(state.chunk_error or "")[:300],
    )


def project_chunk_result(state: ChunkExecutionState) -> dict:
    """Return the diagnostics shape consumed by chunked and resume callers."""
    return {
        "chunk_index": state.chunk_index,
        "page_start": state.page_start,
        "page_end": state.logical_end,
        "effective_page_end": state.effective_end,
        "status": state.chunk_status,
        "batch_id": state.chunk_result.get("batch_id") or None,
        "question_count": (state.chunk_result.get("stats") or {}).get("to_review", 0),
        "error_message": state.chunk_error,
        "diagnostics": resolve_chunk_port(state.namespace, "_slim_chunk_diagnostics")(
            state.chunk_result.get("diagnostics") or {}
        ),
        "stages": state.chunk_result.get("stages") or {},
    }
