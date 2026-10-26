"""Visual split recovery and low-confidence manual-review fallback."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.features.pipeline_split_prose import filter_book_pdf_prose
from app.features.pipeline_split_state import SplitState


def try_visual_split(state: SplitState, *, ports: Callable[[str], Any]) -> None:
    """Try visual split and prose filtering inside the original failure boundary."""
    try:
        from app.features.visual_boundary_detector import (
            detect_visual_boundaries_from_ir,
        )

        doc_ir = ports("_get_blocks_document_ir")(state.split_blocks)
        if doc_ir is not None:
            visual_bounds = detect_visual_boundaries_from_ir(doc_ir)
        else:
            visual_bounds = []
        from app.features.question_splitter import split_by_visual_boundaries

        state.split_diagnostics["visual_boundary"] = {
            "boundary_count": ports("len")(visual_bounds),
            "boundaries": [
                {
                    "page": b.get("page"),
                    "signal": b.get("signal"),
                    "preview": ports("_visual_boundary_preview")(state.split_blocks, b),
                }
                for b in visual_bounds[:20]
            ],
        }
        if ports("len")(visual_bounds) >= 2:
            state.raw_questions = split_by_visual_boundaries(
                state.split_blocks, visual_bounds
            )
            state.warnings.append(
                f"visual_boundary: split {ports('len')(state.raw_questions)} questions via bbox"
            )
            state.split_diagnostics["failure_reason"] = None
            state.split_diagnostics["fallback_created"] = False
            state.split_diagnostics["detection_method"] = "visual_boundary"
            filter_book_pdf_prose(state, ports=ports)
    except ports("Exception") as exc:
        ports("logger").warning("visual boundary detection failed: %s", exc)


def create_review_fallback(state: SplitState, *, ports: Callable[[str], Any]) -> None:
    """Keep book/PDF empty; other imports get a low-confidence review item."""
    if (
        ports("_is_book_import_mode")(state.keyword_arguments.get("import_mode"))
        and ports("str")(state.keyword_arguments.get("source_type") or "").lower()
        == "pdf"
    ):
        state.warnings.append(
            "no questions found in book import; skipped low-confidence fallback review item"
        )
        state.split_diagnostics["fallback_created"] = False
        state.split_diagnostics["failure_reason"] = (
            "book_text_present_but_no_question_boundary"
        )
        state.split_diagnostics["non_question_like_skipped"] = True
    else:
        state.raw_questions = [
            {
                "number": 1,
                "raw_question_text": "\n".join(
                    (
                        ports("str")(b.get("normalized_text") or "").strip()
                        for b in state.text_blocks
                    )
                ),
                "page_start": state.text_blocks[0].get("page", 1),
                "page_end": state.text_blocks[-1].get(
                    "page", state.text_blocks[0].get("page", 1)
                ),
                "has_options": False,
                "option_lines": {},
                "confidence": 0.2,
                "risk_flags": ["fallback_low_confidence"],
            }
        ]
        state.warnings.append(
            "no questions found in document; created low-confidence review item"
        )
        state.split_diagnostics["fallback_created"] = True
        state.split_diagnostics["failure_reason"] = (
            "text_present_but_no_question_boundary"
        )


def resolve_split_fallback(state: SplitState, *, ports: Callable[[str], Any]) -> None:
    """Resolve empty text, visual split, manual fallback and count diagnostics."""
    if not state.raw_questions:
        if state.text_blocks:
            has_boxes = ports("any")((b.get("boxes") for b in state.normalized_blocks))
            if has_boxes:
                try_visual_split(state, ports=ports)
            if not state.raw_questions:
                create_review_fallback(state, ports=ports)
        else:
            state.warnings.append("no questions found in document")
            state.split_diagnostics["fallback_created"] = False
            state.split_diagnostics["failure_reason"] = "no_text_blocks"
    elif ports("len")(state.raw_questions) < ports("len")(state.normalized_blocks):
        state.warnings.append(
            f"{ports('len')(state.normalized_blocks) - ports('len')(state.raw_questions)} blocks produced no questions"
        )
        state.split_diagnostics["fallback_created"] = False
        state.split_diagnostics["failure_reason"] = None
    else:
        state.split_diagnostics["fallback_created"] = False
        state.split_diagnostics["failure_reason"] = None
