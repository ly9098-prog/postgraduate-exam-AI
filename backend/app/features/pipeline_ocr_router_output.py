"""Final block filtering, metrics and correction-stage response."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.features.pipeline_ocr_router_state import RouterStageState


def filter_corrected_blocks(
    state: RouterStageState, *, ports: Callable[[str], Any]
) -> None:
    """Fill defensive gaps and filter sensitive text before final model statistics."""
    for idx, b in ports("enumerate")(state.corrected_blocks):
        if b is None:
            state.corrected_blocks[idx] = state.normalized_blocks[idx]
    state.corrected_blocks = [b for b in state.corrected_blocks if b is not None]
    if state.router_config.get("ocr_filter_sensitive", True):
        filtered_count = 0
        for b in state.corrected_blocks:
            text = b.get("normalized_text", "")
            filtered = ports("_filter_sensitive")(text)
            if filtered != text:
                b["normalized_text"] = filtered
                filtered_count += 1
        if filtered_count:
            ports("logger").debug(
                "ocr_filter_sensitive: filtered %d blocks", filtered_count
            )


def finish_router_stage(
    state: RouterStageState, *, ports: Callable[[str], Any]
) -> dict:
    """Flush metrics before returning final references and aggregate diagnostics."""
    used_models = {
        c.get("model_used") for c in state.corrections if c.get("model_used")
    }
    state.stats["model_used"] = (
        ", ".join(ports("sorted")(used_models)) if used_models else "none"
    )
    warnings: list[str] = []
    if state.stats["corrected_blocks"] > 0:
        warnings.append(
            f"Router corrected {state.stats['corrected_blocks']}/{state.stats['total_blocks']} blocks (model: {state.stats['model_used']})"
        )
    state.metrics.flush(
        extra={
            "stats": state.stats,
            "used_models": ports("sorted")(used_models) if used_models else [],
        }
    )
    return {
        "normalized_blocks": state.corrected_blocks,
        "ocr_correction_diagnostics": {
            "stats": state.stats,
            "corrections": state.corrections,
            **state.model_call_totals,
        },
        "quality_gate_shadow_records": state.quality_gate_shadow_records,
        "warnings": warnings,
    }
