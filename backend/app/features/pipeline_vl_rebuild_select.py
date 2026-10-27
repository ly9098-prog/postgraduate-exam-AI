"""VL rebuild select with historical live ports and outer try ownership."""

from __future__ import annotations

from app.features.pipeline_vl_rebuild_state import VlRebuildState


def select_vl_rebuild_page_text(
    state: VlRebuildState, page_idx: int, png_bytes: bytes, pw: int, ph: int
) -> None:
    """Run PP-OCR and VL per page and keep the richer option set with table metadata."""
    state.best_text = ""
    state.pp_text = ""
    state.pp_opt_count = 0
    state.page_table_blocks = []
    if not state._is_cloud_vl:
        try:
            from app.services.ocr_service import ocr_raw_text

            state.pp_text = ocr_raw_text(png_bytes)
            if state.detect_options_from_text(state.pp_text):
                state.best_text = state.pp_text
                state.pp_opt_count = state.port("len")(
                    state.extract_options_from_text(state.pp_text)
                )
                state.port("logger").info(
                    "VL_REBUILD page %d: PP-OCRv4 (%d chars, %d options detected)",
                    page_idx,
                    state.port("len")(state.pp_text),
                    state.pp_opt_count,
                )
        except state.port("Exception") as exc:
            state.port("logger").warning(
                "VL_REBUILD PP-OCRv4 failed page %d: %s", page_idx, exc
            )
    if state.pp_opt_count < 4:
        _select_vl_candidate(state, page_idx, png_bytes)


def _select_vl_candidate(
    state: VlRebuildState, page_idx: int, png_bytes: bytes
) -> None:
    """Call VL and retain the richer candidate while preserving table metadata."""
    ctx = {
        "page_num": page_idx,
        "filename": f"page_{page_idx}.png",
        "entry_point": "vl_rebuild",
    }
    result = state.port("_run_coro_in_loop")(
        state.router.fix(image=png_bytes, ocr_text="", context=ctx)
    )
    if not (result and result.fixed_text):
        return
    vl_raw = result.fixed_text.strip()
    state.page_table_blocks = [
        item
        for item in (state.port("getattr")(result, "metadata", None) or {}).get(
            "layout_blocks"
        )
        or []
        if state.port("isinstance")(item, state.port("dict"))
        and state.port("str")(item.get("type") or item.get("label") or "").lower()
        in {"table", "table_image", "table_caption"}
    ]
    repaired = state.repair_option_structure(
        vl_raw, state.pp_text, state.values["original_raw_text"]
    )
    vl_has_opts = state.detect_options_from_text(repaired)
    vl_text = repaired if vl_has_opts else vl_raw
    vl_opt_count = (
        state.port("len")(state.extract_options_from_text(vl_text))
        if vl_has_opts
        else 0
    )
    _choose_vl_text(state, page_idx, vl_text, vl_opt_count, vl_has_opts)


def _choose_vl_text(
    state: VlRebuildState,
    page_idx: int,
    vl_text: str,
    vl_opt_count: int,
    vl_has_opts: bool,
) -> None:
    """Prefer more VL options; otherwise fill an empty PP candidate."""
    if vl_opt_count > state.pp_opt_count:
        state.best_text = vl_text
        state.port("logger").info(
            "VL_REBUILD page %d: switching to VL (%d chars, %d options vs PP-OCR's %d)",
            page_idx,
            state.port("len")(state.best_text),
            vl_opt_count,
            state.pp_opt_count,
        )
    elif not state.best_text:
        state.best_text = vl_text
        state.port("logger").info(
            "VL_REBUILD page %d: using VL (%d chars, options=%s)",
            page_idx,
            state.port("len")(state.best_text),
            vl_has_opts,
        )
