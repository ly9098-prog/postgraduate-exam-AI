"""Warnings, failed-page aliases, DocumentIR and OCR monitoring summary."""

from __future__ import annotations

from app.features.pipeline_scanned_state import ScannedPdfState


def finish_scanned_pdf(state: ScannedPdfState) -> list[dict]:
    if state.timed_out and state.blocks:
        state.blocks[0].setdefault("_warnings", [])
        state.blocks[0]["_warnings"].append(
            f"ocr_timeout: processed {state.port('len')(state.blocks)} blocks in {state.timeout}s limit"
        )
    elif state.max_pages > 0 and state.pages_in_range > state.max_pages and state.blocks:
        state.blocks[0].setdefault("_warnings", [])
        state.blocks[0]["_warnings"].append(
            f"ocr_pages_truncated: processed {state.pages_to_process}/{state.pages_in_range} selected pages"
        )
    if state.ocr_text_fallback_unavailable_pages and state.blocks:
        pages = state.port("sorted")(state.ocr_text_fallback_unavailable_pages)
        state.blocks[0]["_ocr_text_fallback_unavailable_pages"] = pages
        state.blocks[0]["_ocr_runtime_failed_pages"] = pages
    doc_ir = state.port("_blocks_to_document_ir")(state.blocks, pipeline_id=state.pipeline_id)
    if doc_ir and state.blocks:
        state.blocks[0]["_document_ir"] = doc_ir
    ocr_duration = state.time.monotonic() - state.start_time
    state.port("set_tag")("ocr.pages_total", state.pages_to_process)
    state.port("set_tag")(
        "ocr.pages_processed",
        state.port("len")(state.port("set")((b.get("page") for b in state.blocks))),
    )
    state.port("set_tag")("ocr.blocks", state.port("len")(state.blocks))
    state.port("set_tag")("ocr.duration_ms", state.port("int")(ocr_duration * 1000))
    if state.timed_out:
        state.port("set_tag")("ocr.timed_out", True)
    failed_count = state.port("len")(state.ocr_text_fallback_unavailable_pages)
    if failed_count:
        state.port("set_tag")("ocr.failed_pages", failed_count)
    return state.blocks
