"""Prepare ordered split inputs and layout fallback."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.features.pipeline_split_state import SplitState


def initialize_split_input(state: SplitState, *, ports: Callable[[str], Any]) -> None:
    """Resolve strategy and import mode before cross-page work."""
    state.strategy = state.keyword_arguments.get("strategy") or {}
    state.gap_tolerance = state.strategy.get("question_number_gap_tolerance", 10)
    state.raw_im = state.keyword_arguments.get("import_mode")
    if ports("isinstance")(state.raw_im, ports("ImportMode")):
        state.import_mode_str = state.raw_im.value
    else:
        state.import_mode_str = ports("str")(state.raw_im or "").lower() or None
    state.split_blocks = state.normalized_blocks
    state.warnings = []
    state.extra_data = {}


def merge_split_pages(state: SplitState, *, ports: Callable[[str], Any]) -> None:
    """Accept merged blocks and merge diagnostics only when links exist."""
    xp_blocks, xp_links, xp_warnings, xp_merge_results = ports(
        "_merge_cross_page_blocks"
    )(state.split_blocks)
    if xp_links:
        state.split_blocks = xp_blocks
        state.warnings.extend(xp_warnings)
        state.warnings.append(f"cross_page: {ports('len')(xp_links)} link(s) applied")
        state.extra_data["cross_page_merge_results"] = xp_merge_results


def filter_split_layout(state: SplitState, *, ports: Callable[[str], Any]) -> None:
    """Filter original book/PDF blocks; ordinary failures retain accepted input."""
    state.layout_filter_diagnostics = {
        "enabled": False,
        "pages_considered": 0,
        "filtered_line_count": 0,
        "kept_line_count": 0,
        "region_signals": [],
    }
    if (
        state.import_mode_str == "book"
        and ports("str")(state.keyword_arguments.get("source_type") or "").lower()
        == "pdf"
        and ports("any")((b.get("boxes") for b in state.normalized_blocks))
    ):
        try:
            from app.features.visual_boundary_detector import (
                filter_book_layout_blocks_from_ir,
            )

            doc_ir = ports("_get_blocks_document_ir")(state.normalized_blocks)
            if doc_ir is not None:
                state.split_blocks, state.layout_filter_diagnostics = (
                    filter_book_layout_blocks_from_ir(doc_ir)
                )
            else:
                state.split_blocks, state.layout_filter_diagnostics = (
                    state.normalized_blocks,
                    {"error": "no_document_ir"},
                )
        except ports("Exception") as exc:
            ports("logger").warning("book layout filter failed: %s", exc)


def resolve_split_options(state: SplitState, *, ports: Callable[[str], Any]) -> None:
    """Read layout, split mode and registry after layout filtering."""
    state.layout_result = state.keyword_arguments.get("layout_result") or {}
    state.split_mode = state.keyword_arguments.get("split_mode", "standard")
    state.frozen_option_registry = (
        state.keyword_arguments.get("frozen_option_registry") or {}
    )
