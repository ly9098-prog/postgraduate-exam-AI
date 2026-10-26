"""Chunk-overlap filtering and truncated-option warnings."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.features.pipeline_split_state import SplitState


def warn_unclosed_boundary(state: SplitState, *, ports: Callable[[str], Any]) -> None:
    """Warn only for an ABC question without D/E close to the chunk edge."""
    if state.raw_questions:
        last = state.raw_questions[-1]
        last_page_end = last.get("page_end") or 0
        opts = last.get("option_lines") or {}
        opt_keys = {ports("str")(k).upper() for k in opts.keys()}
        near_boundary = ports("abs")(last_page_end - state.logical_end) <= 1
        looks_truncated = (
            "A" in opt_keys
            and "B" in opt_keys
            and ("C" in opt_keys)
            and ("D" not in opt_keys)
            and ("E" not in opt_keys)
        )
        if near_boundary and ports("bool")(last.get("has_options")) and looks_truncated:
            state.warnings.append(
                f"chunk_boundary_unclosed: q{last.get('number')} may span next chunk (page_end={last_page_end}, logical_end={state.logical_end})"
            )
            state.split_diagnostics["boundary_unclosed_question"] = last.get("number")


def deduplicate_chunk_overlap(
    state: SplitState, *, ports: Callable[[str], Any]
) -> None:
    """Drop seen hashes only in overlap territory; retain partial set updates."""
    state.seen_hashes = state.keyword_arguments.get("_chunk_seen_hashes")
    state.logical_end = state.keyword_arguments.get("_chunk_logical_end")
    if state.seen_hashes is not None and state.logical_end is not None:
        kept: list[dict] = []
        skipped_numbers: list[int] = []
        for q in state.raw_questions:
            page_start = q.get("page_start") or 0
            qhash = ports("_compute_overlap_hash")(q)
            if (
                qhash is not None
                and qhash in state.seen_hashes
                and (page_start > state.logical_end)
            ):
                num = q.get("number")
                if num is not None:
                    skipped_numbers.append(num)
                else:
                    skipped_numbers.append(-1)
                continue
            kept.append(q)
            if qhash is not None:
                state.seen_hashes.add(qhash)
        if skipped_numbers:
            state.warnings.append(
                f"boundary_overlap_skipped: {ports('sorted')(ports('set')(skipped_numbers))}"
            )
            state.split_diagnostics["overlap_skipped_numbers"] = ports("sorted")(
                ports("set")(skipped_numbers)
            )
        state.raw_questions = kept
        warn_unclosed_boundary(state, ports=ports)
