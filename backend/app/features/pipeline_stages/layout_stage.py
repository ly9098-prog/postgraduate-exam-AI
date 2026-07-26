"""Layout reconstruction stage — spatial layout analysis before question splitting.

Extracted from pipeline_orchestrator.py integration point.

Runs between text normalization and structure analysis.
Uses bbox + geometry heuristics only — no LLM dependency.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.document_ir import DocumentIR


import logging
from typing import Any

from app.features.layout_reconstruction import (
    needs_fallback,
    reconstruct_layout,
)

logger = logging.getLogger(__name__)


def run_layout_reconstruction_stage(
    normalized_blocks: list[dict],
    **kwargs: Any,
) -> dict:
    """Run layout reconstruction on normalized blocks.

    Analyzes spatial layout using OCR bbox data:
    - Column detection (single/double-column)
    - Option block clustering (A./B./C./D.)
    - Reading order reconstruction
    - Layout confidence scoring

    Args:
        normalized_blocks: OCR blocks after text normalization.
            Each block should have: text/normalized_text, boxes (with bbox),
            page, page_width, page_height.

    Returns:
        dict with keys:
            layout_blocks: enriched blocks with layout_info attached.
            layout_result: full layout reconstruction result dict.
            warnings: list of warning strings.
    """
    if not normalized_blocks:
        return {
            "layout_blocks": [],
            "layout_result": {
                "layout_blocks": [],
                "option_groups": {},
                "layout_confidence": 1.0,
                "option_detection_score": 0.0,
                "reading_order": [],
                "option_detection_failed": False,
                "warnings": ["layout_stage: empty blocks"],
            },
            "warnings": ["layout_stage: empty blocks"],
        }

    # Check if any blocks have bbox data
    has_boxes = any(
        block.get("boxes") and len(block["boxes"]) > 0
        for block in normalized_blocks
    )

    layout_result = reconstruct_layout(normalized_blocks)

    warnings: list[str] = list(layout_result.get("warnings", []))
    layout_confidence = layout_result.get("layout_confidence", 1.0)

    if needs_fallback(layout_result):
        warnings.append(
            f"layout_reconstruction: confidence={layout_confidence:.2f}, "
            "option_detection_failed="
            f"{layout_result.get('option_detection_failed', False)}"
        )

    if not has_boxes:
        warnings.append(
            "layout_reconstruction: no bbox data available, "
            "layout analysis limited"
        )

    return {
        "layout_blocks": normalized_blocks,  # enriched in-place
        "layout_result": layout_result,
        "layout_confidence": layout_confidence,
        "warnings": warnings,
    }


def run_layout_reconstruction_stage_from_ir(
    doc: DocumentIR,
    **kwargs: Any,
) -> dict:
    """DocumentIR entry point for run_layout_reconstruction_stage."""
    from app.core.document_ir import document_ir_to_blocks
    blocks = document_ir_to_blocks(doc)
    return run_layout_reconstruction_stage(blocks, **kwargs)
