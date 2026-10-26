"""Per-candidate metadata and failure or unchanged projection."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.features.pipeline_ocr_router_state import RouterCandidate, RouterStageState


def record_failed_candidate(
    state: RouterStageState, candidate: RouterCandidate, *, ports: Callable[[str], Any]
) -> None:
    """Retain original block and failure trace when a gathered child failed."""
    ports("logger").warning(
        "router fix block %d failed: %s", candidate.idx, candidate.fix_result
    )
    state.corrected_blocks[candidate.idx] = candidate.block
    state.corrections.append(
        {
            "block_index": candidate.block.get("block_index", 0),
            "page": candidate.block.get("page", 1),
            "noise_score": ports("round")(candidate.noise_score, 3),
            "structure_score": ports("round")(candidate.structure_score, 3),
            "corrected": False,
            "reason": f"exception: {candidate.fix_result}",
            "before_preview": ports("_safe_text_summary")(candidate.text),
        }
    )
    state.metrics.record_failure(model="exception", before=candidate.text)


def project_candidate_metadata(
    state: RouterStageState, candidate: RouterCandidate, *, ports: Callable[[str], Any]
) -> None:
    """Copy a returned candidate and preserve bounded table layout metadata."""
    _, candidate.result = candidate.fix_result
    candidate.new_block = ports("dict")(candidate.block)
    router_stats = (ports("getattr")(candidate.result, "metadata", None) or {}).get(
        "router_call_stats"
    ) or {}
    for key in state.model_call_totals:
        state.model_call_totals[key] += ports("int")(router_stats.get(key, 0) or 0)
    layout_blocks = (ports("getattr")(candidate.result, "metadata", None) or {}).get(
        "layout_blocks"
    ) or []
    table_layout_blocks = [
        item
        for item in layout_blocks
        if ports("isinstance")(item, ports("dict"))
        and ports("str")(item.get("type") or item.get("label") or "").lower()
        in {"table", "table_image", "table_caption"}
    ]
    if table_layout_blocks:
        candidate.new_block["vl_layout_blocks"] = table_layout_blocks
    candidate.is_vl = "paddleocr-vl" in (candidate.result.model_used or "")


def record_unchanged_candidate(
    state: RouterStageState, candidate: RouterCandidate, *, ports: Callable[[str], Any]
) -> None:
    """Record unchanged or ineligible text without a safety evaluation."""
    state.corrections.append(
        {
            "block_index": candidate.block.get("block_index", 0),
            "page": candidate.block.get("page", 1),
            "noise_score": ports("round")(candidate.noise_score, 3),
            "structure_score": ports("round")(candidate.structure_score, 3),
            "corrected": False,
            "reason": candidate.result.raw_response or "no_change",
            "before_preview": ports("_safe_text_summary")(candidate.text),
        }
    )
    state.metrics.record_unchanged(
        model=candidate.result.model_used, before=candidate.text
    )
