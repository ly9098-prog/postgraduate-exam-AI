"""VL rebuild source loading with historical local imports."""

from __future__ import annotations

from app.features.pipeline_vl_rebuild_state import VlRebuildState


def load_vl_rebuild_sources(state: VlRebuildState) -> bool:
    """Construct the router and render PDF pages or read the image file before any OCR call."""
    from app.features.ocr_fix.router import STRATEGY_MANUAL, OCRFixRouter

    state.router = OCRFixRouter()
    state.router.configure(
        {
            "ocr_fix_strategy": STRATEGY_MANUAL,
            "ocr_fix_model": "paddleocr-vl",
            "paddleocr_vl_api_token": state.api_token,
            "paddleocr_vl_base_url": state.base_url,
            "paddleocr_vl_model": state.model,
        }
    )
    state.new_blocks = []
    state.page_batches = []
    if state.is_pdf:
        _load_pdf_sources(state)
    else:
        if not _load_image_sources(state):
            return False
    _load_candidate_ports(state)
    return True


def _load_pdf_sources(state: VlRebuildState) -> None:
    """Render every PDF page before OCR, preserving close-before-OCR behavior."""
    import fitz

    doc = fitz.open(state.values["file_path"], filetype="pdf")
    try:
        total_pages = state.port("len")(doc)
        state.page_dim = {}
        for block in state.values["original_blocks"]:
            page = block.get("page") or block.get("page_index") or 0
            width = block.get("page_width") or 800
            height = block.get("page_height") or 1200
            if page not in state.page_dim:
                state.page_dim[page] = (width, height)
        for page_num in state.port("range")(total_pages):
            page_idx = page_num + 1
            pix = doc[page_num].get_pixmap(dpi=150)
            png_bytes = pix.tobytes("png")
            width, height = state.page_dim.get(page_idx, (pix.width, pix.height))
            state.page_batches.append((page_idx, png_bytes, width, height))
    finally:
        doc.close()


def _load_image_sources(state: VlRebuildState) -> bool:
    """Read the image at its historical import point and keep its fallback dimensions."""
    import os

    if not os.path.isfile(state.values["file_path"]):
        state.port("logger").warning(
            "VL_REBUILD: image file not found: %s", state.values["file_path"]
        )
        return False
    with state.port("open")(state.values["file_path"], "rb") as source:
        image_bytes = source.read()
    width, height = 800, 1200
    if state.values["original_blocks"]:
        first = state.values["original_blocks"][0]
        width = first.get("page_width") or width
        height = first.get("page_height") or height
    state.page_batches.append((1, image_bytes, width, height))
    return True


def _load_candidate_ports(state: VlRebuildState) -> None:
    """Capture profile and classifier ports after all source bytes are ready."""
    from app.core.deployment_profile import (
        DeploymentProfile,
        detect_deployment_profile,
    )
    from app.features.ocr_correction_common import repair_option_structure
    from app.features.question_type_classifier import (
        detect_options_from_text,
        extract_options_from_text,
    )

    state._is_cloud_vl = detect_deployment_profile() == DeploymentProfile.CLOUD_API
    state.repair_option_structure = repair_option_structure
    state.detect_options_from_text = detect_options_from_text
    state.extract_options_from_text = extract_options_from_text
