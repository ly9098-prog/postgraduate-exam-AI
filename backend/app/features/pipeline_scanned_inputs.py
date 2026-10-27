"""Local profile guard, PDF acquisition and selected-page preparation."""

from __future__ import annotations

from app.features.pipeline_scanned_state import ScannedPdfState


def load_scanned_pdf(
    content_or_path: bytes | str,
    pipeline_id: str,
    page_start: int,
    page_end: int | None,
    *,
    namespace: dict,
) -> ScannedPdfState:
    state = ScannedPdfState(namespace, content_or_path, pipeline_id, page_start, page_end)
    import gc
    import time

    import fitz  # noqa: F401

    from app.core.config import settings
    from app.core.deployment_profile import DeploymentProfile, detect_deployment_profile
    from app.core.ocr_profile import get_ocr_profile
    from app.services.ocr_service import ocr_pages, ocr_pages_with_boxes

    if detect_deployment_profile() == DeploymentProfile.CLOUD_API:
        raise state.port("RuntimeError")(
            "_ocr_scanned_pdf is forbidden in cloud_api deployment. Use OCRGateway.recognize_pages() instead."
        )
    state.gc = gc
    state.time = time
    state.ocr_pages = ocr_pages
    state.ocr_pages_with_boxes = ocr_pages_with_boxes
    state.profile = get_ocr_profile()
    state.max_pages = settings.MAX_OCR_PAGES
    state.timeout = state.profile.timeout_seconds
    state.batch_size = state.profile.max_workers
    state.doc = state.port("_open_pdf_doc")(state.content_or_path)
    state.total_pages = state.port("len")(state.doc)
    initialize_scanned_pdf(state)
    return state


def initialize_scanned_pdf(state: ScannedPdfState) -> None:
    state.port("set_tag")("ocr.engine", "PaddleOCR")
    ocr_source = (
        state.port("str")(state.content_or_path)
        if state.port("isinstance")(
            state.content_or_path, (state.port("str"), state.port("os").PathLike)
        )
        else state.pipeline_id
    )
    state.port("set_tag")("ocr.source", ocr_source[:200])
    state.start_idx = state.port("max")(0, (state.page_start or 1) - 1)
    state.end_idx = state.port("min")(state.total_pages, state.page_end or state.total_pages)
    state.pages_in_range = state.end_idx - state.start_idx
    state.pages_to_process = (
        state.port("min")(state.pages_in_range, state.max_pages)
        if state.max_pages > 0
        else state.pages_in_range
    )
    state.blocks = []
    state.page_dimensions = {}
    state.ocr_text_fallback_unavailable_pages = state.port("set")()
    state.timed_out = False
    state.start_time = state.time.monotonic()
    state.port("logger").info(
        "OCR 开始：共 %d 页待处理（第 %d-%d 页）",
        state.pages_to_process,
        state.start_idx + 1,
        state.end_idx,
    )
    if state.pipeline_id:
        state.port("_ocr_progress")[state.pipeline_id] = f"0/{state.pages_to_process} pages"
