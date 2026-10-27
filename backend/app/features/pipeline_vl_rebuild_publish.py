"""VL rebuild publish with historical live ports and outer try ownership."""

from __future__ import annotations

from app.features.pipeline_vl_rebuild_state import VlRebuildState


def publish_vl_rebuild_block(
    state: VlRebuildState, page_idx: int, png_bytes: bytes, pw: int, ph: int
) -> bool:
    """Run final recovery, clean page markers, and append the block or fail the whole call."""
    if state.best_text:
        from app.features.option_recovery import recover_options_from_sources

        recovered = recover_options_from_sources(
            state.best_text, state.pp_text, state.values["original_raw_text"]
        )
        if state.port("len")(recovered.options) >= state.port("max")(
            2,
            state.port("len")(state.extract_options_from_text(state.best_text)),
        ):
            state.best_text = recovered.text
            if recovered.repaired_keys:
                state.port("logger").info(
                    "VL_REBUILD page %d: Phase 8 recovered keys=%s mirror_repairs=%d",
                    page_idx,
                    recovered.repaired_keys,
                    recovered.mirror_repairs,
                )
        state.best_text = (
            state.port("re")
            .sub(r"(?:^|\n)\s*<\d*>\s*(?:\n|$)", r"\n", state.best_text)
            .strip()
        )
        state.new_blocks.append(
            {
                "page": page_idx,
                "page_index": page_idx,
                "block_index": state.port("len")(state.new_blocks),
                "text": state.best_text,
                "normalized_text": state.best_text,
                "boxes": [],
                "page_width": pw,
                "page_height": ph,
                "source": "vl_rebuild",
                "has_boxes": False,
                "vl_layout_blocks": state.page_table_blocks,
            }
        )
    return True
