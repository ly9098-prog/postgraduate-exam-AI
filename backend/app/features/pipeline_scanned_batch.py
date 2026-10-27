"""Bounded rendering, reset/retry fallback and original block projection."""

from __future__ import annotations

from app.features.pipeline_scanned_state import ScannedPdfState


def render_scanned_batch(
    state: ScannedPdfState, batch_start: int, batch_end: int
) -> list[tuple[int, bytes]]:
    batch_images = []
    for i in state.port("range")(batch_start, batch_end):
        page_idx = state.start_idx + i
        # Read per page so runtime DPI changes keep their original timing.
        _ocr_dpi = state.port("int")(state.port("os").environ.get("OCR_RENDER_DPI", "200"))
        pix = state.doc[page_idx].get_pixmap(dpi=_ocr_dpi)
        png_bytes = pix.tobytes("png")
        state.page_dimensions[page_idx + 1] = (pix.width, pix.height)
        del pix
        batch_images.append((page_idx + 1, png_bytes))
    return batch_images


def fallback_scanned_batch(
    state: ScannedPdfState, batch_images: list[tuple[int, bytes]], results: dict
) -> dict:
    batch_image_map = {idx: png for idx, png in batch_images}
    failed_images = [
        (idx, batch_image_map[idx])
        for idx, result in results.items()
        if result.failed and idx in batch_image_map
    ]
    try:
        from app.services.ocr_service import reset_ocr_engine

        reset_ocr_engine()
        fallback_results = state.ocr_pages(failed_images) if failed_images else {}
    except (state.port("RuntimeError"), state.port("Exception")) as exc:
        state.port("logger").warning(
            "OCR text fallback failed: %s — retrying with another reset", exc
        )
        try:
            reset_ocr_engine()
            fallback_results = state.ocr_pages(failed_images) if failed_images else {}
        except state.port("Exception") as exc2:
            state.port("logger").warning("OCR text fallback retry also failed: %s", exc2)
            fallback_results = {}
            state.ocr_text_fallback_unavailable_pages.update((idx for idx, _ in failed_images))
    return fallback_results


def append_scanned_page(
    state: ScannedPdfState, page_idx: int, results: dict, fallback_results: dict
) -> None:
    result = results[page_idx]
    pw, ph = state.page_dimensions[page_idx]
    if result.failed:
        text = fallback_results.get(page_idx, "")
        if text.strip():
            state.blocks.append(
                {
                    "page": page_idx,
                    "page_index": page_idx,
                    "block_index": state.port("len")(state.blocks),
                    "text": text,
                    "boxes": [],
                    "page_width": pw,
                    "page_height": ph,
                    "source": "ocr_text_fallback",
                    "has_boxes": False,
                    "_ocr_boxes_failed": True,
                }
            )
        else:
            state.ocr_text_fallback_unavailable_pages.add(page_idx)
        return
    text = result.text
    if text.strip():
        boxes = result.boxes or []
        state.blocks.append(
            {
                "page": page_idx,
                "page_index": page_idx,
                "block_index": state.port("len")(state.blocks),
                "text": text,
                "boxes": boxes,
                "page_width": pw,
                "page_height": ph,
                "source": "ocr_boxes",
                "has_boxes": state.port("bool")(boxes),
            }
        )
