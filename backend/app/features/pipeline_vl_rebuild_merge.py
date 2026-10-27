"""VL rebuild merge with historical live ports and outer try ownership."""

from __future__ import annotations

from app.features.pipeline_vl_rebuild_state import VlRebuildState


def merge_original_options_into_text(
    state: VlRebuildState, page_idx: int, png_bytes: bytes, pw: int, ph: int
) -> None:
    """Append missing original options line by line using the strict prefix."""
    if state.best_text and state.values["original_raw_text"]:
        current_opts = state.extract_options_from_text(state.best_text)
        original_opts = state.extract_options_from_text(
            state.values["original_raw_text"]
        )
        if original_opts:
            missing = state.port("set")(original_opts.keys()) - state.port("set")(
                current_opts.keys()
            )
            if missing:
                for line in state.values["original_raw_text"].split("\n"):
                    for key in state.port("list")(missing):
                        prefix = f"{key}."
                        if line.strip().startswith(prefix):
                            state.best_text = state.best_text + "\n" + line
                            current_opts[key] = original_opts[key]
                            missing.remove(key)
                            state.port("logger").info(
                                "VL_REBUILD page %d: merged option %s from original_raw_text (now %d options)",
                                page_idx,
                                key,
                                state.port("len")(current_opts),
                            )
                            break
