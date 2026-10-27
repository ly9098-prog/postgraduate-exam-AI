"""Batch-level time limits and resource-close boundary for local OCR."""

from __future__ import annotations

from app.features.pipeline_scanned_batch import (
    append_scanned_page,
    fallback_scanned_batch,
    render_scanned_batch,
)
from app.features.pipeline_scanned_inputs import (
    initialize_scanned_pdf,
    load_scanned_pdf,
)
from app.features.pipeline_scanned_output import finish_scanned_pdf
from app.features.pipeline_scanned_results import validate_scanned_results
from app.features.pipeline_scanned_state import ScannedPdfState


def run_scanned_pdf(
    content_or_path: bytes | str,
    pipeline_id: str,
    page_start: int,
    page_end: int | None,
    *,
    namespace: dict,
) -> list[dict]:
    state = load_scanned_pdf(
        content_or_path, pipeline_id, page_start, page_end, namespace=namespace
    )
    try:
        initialize_scanned_pdf(state)
        run_scanned_batches(state)
    except BaseException as error:
        try:
            release_scanned_pdf(state)
        except BaseException as cleanup_error:
            BaseException.add_note(
                error, f"scanned PDF cleanup also failed ({type(cleanup_error).__name__})"
            )
        raise
    else:
        release_scanned_pdf(state)
    return finish_scanned_pdf(state)


def release_scanned_pdf(state: ScannedPdfState) -> None:
    """Close once; clear progress only after this invocation published it."""
    close_error = None
    try:
        state.doc.close()
    except BaseException as error:
        close_error = error
    try:
        if state.progress_started:
            state.port("_ocr_progress").pop(state.pipeline_id, None)
    except BaseException as error:
        if close_error is None:
            raise
        BaseException.add_note(
            close_error, f"scanned PDF progress cleanup also failed ({type(error).__name__})"
        )
    if close_error is not None:
        raise close_error


def run_scanned_batches(state: ScannedPdfState) -> None:
    for batch_start in state.port("range")(0, state.pages_to_process, state.batch_size):
        elapsed = state.time.monotonic() - state.start_time
        if state.timeout > 0 and elapsed >= state.timeout:
            state.port("logger").warning(
                "OCR 超时中断：已用 %.1fs（限制 %ds），处理了 %d/%d 页",
                elapsed,
                state.timeout,
                batch_start,
                state.pages_to_process,
            )
            state.timed_out = True
            break
        process_scanned_batch(state, batch_start)


def process_scanned_batch(state: ScannedPdfState, batch_start: int) -> None:
    batch_end = state.port("min")(batch_start + state.batch_size, state.pages_to_process)
    batch_images = render_scanned_batch(state, batch_start, batch_end)
    results = state.ocr_pages_with_boxes(batch_images, skip_rotation=True)
    validate_scanned_results(batch_images, results)
    fallback_results = fallback_scanned_batch(state, batch_images, results)
    del batch_images
    state.gc.collect()
    for page_idx in state.port("sorted")(results.keys()):
        append_scanned_page(state, page_idx, results, fallback_results)
    state.port("logger").info(
        "OCR 进度：%d/%d 页已处理（%.1fs）",
        batch_end,
        state.pages_to_process,
        state.time.monotonic() - state.start_time,
    )
    if state.pipeline_id:
        state.port("_ocr_progress")[state.pipeline_id] = (
            f"{batch_end}/{state.pages_to_process} pages"
        )
