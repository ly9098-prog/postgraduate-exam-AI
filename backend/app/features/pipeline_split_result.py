"""Pre-filter split diagnostics and final frozen-question projection."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.features.pipeline_split_binding import finalize_split_binding
from app.features.pipeline_split_state import SplitState


def initialize_split_diagnostics(
    state: SplitState, *, ports: Callable[[str], Any]
) -> None:
    """Snapshot pre-filter counts and question hash before fallback or dedup."""
    state.text_blocks = [
        b
        for b in state.split_blocks
        if ports("str")(b.get("normalized_text") or "").strip()
    ]
    state.split_diagnostics = {
        "normalized_block_count": ports("len")(state.normalized_blocks),
        "text_block_count": ports("len")(state.text_blocks),
        "raw_question_count": ports("len")(state.raw_questions),
        "split_mode": state.split_mode,
        "book_prose_downgraded": ports("sum")(
            (
                1
                for q in state.raw_questions
                if "book_pdf_prose_like" in (q.get("risk_flags") or [])
            )
        ),
        "layout_filter": state.layout_filter_diagnostics,
        "raw_questions_hash": ports("_safe_hash_preview")(state.raw_questions),
        "failure_reason": None,
    }


def finish_split_result(state: SplitState, *, ports: Callable[[str], Any]) -> dict:
    """Observe, apply frozen options, log and return the final question references."""
    finalize_split_binding(state)
    ports("_log_multi_blank_stage")(
        "split",
        state.raw_questions,
        source_type=state.keyword_arguments.get("source_type"),
        import_mode=state.import_mode_str,
    )
    if state.frozen_option_registry:
        ports("_apply_frozen_options")(
            state.raw_questions,
            state.frozen_option_registry,
            freeze_checksum=state.keyword_arguments.get("freeze_checksum"),
            normalized_blocks=state.split_blocks,
        )
    for q in state.raw_questions:
        opts = q.get("option_lines") or {}
        opt_summary = (
            ", ".join(
                (
                    f"{k}: {ports('str')(v)[:40]}"
                    for k, v in ports("sorted")(opts.items())
                )
            )
            or "(无选项)"
        )
        ports("logger").info(
            "【OCR-6】题目解析结果 | number=%s page=%s has_options=%s options=%s%s\n  └─ 题干: %.200s",
            q.get("number", "?"),
            q.get("page_start", "?"),
            q.get("has_options", False),
            opt_summary[:120],
            " [FROZEN]" if q.get("is_frozen") else "",
            ports("str")(q.get("raw_question_text") or ""),
        )
    return {
        "raw_questions": state.raw_questions,
        "split_count": ports("len")(state.raw_questions),
        "split_diagnostics": state.split_diagnostics,
        "warnings": state.warnings,
        **state.extra_data,
    }
