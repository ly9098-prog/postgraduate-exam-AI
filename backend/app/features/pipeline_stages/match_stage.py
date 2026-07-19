"""Answer matching stage — match answers and explanations to questions.

Extracted from ``pipeline_orchestrator.py:_run_match`` (P5-2).
"""

from __future__ import annotations

import logging

from app.features.answer_matcher import match_answers

logger = logging.getLogger(__name__)


def run_match_stage(
    raw_questions: list[dict],
    normalized_blocks: list[dict],
    structure: dict | None = None,
) -> dict:
    """Match answers and explanations to questions.

    Returns:
        dict with ``matched``, ``unmatched``, ``matched_count``, ``warnings`` keys.
    """
    result = match_answers(raw_questions, normalized_blocks, structure=structure)

    matched = result.get("matched", [])
    unmatched = result.get("unmatched", [])

    warnings: list[str] = []
    if unmatched:
        warnings.append(f"{len(unmatched)} questions have no matched answer")

    return {
        "matched": matched,
        "unmatched": unmatched,
        "matched_count": len(matched),
        "warnings": warnings,
    }


def run_match_stage_from_ir(
    raw_questions: list[dict],
    doc: "DocumentIR",
    structure: dict | None = None,
) -> dict:
    """DocumentIR entry point for run_match_stage."""
    from app.core.document_ir import document_ir_to_blocks
    blocks = document_ir_to_blocks(doc)
    return run_match_stage(raw_questions, blocks, structure=structure)
