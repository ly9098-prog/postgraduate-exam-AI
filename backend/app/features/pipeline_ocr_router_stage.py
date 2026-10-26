"""Coordinate OCR correction while retaining budget and quality boundaries."""

from __future__ import annotations

from functools import partial
from typing import Any

from app.features.pipeline_ocr_router_classification import (
    classify_router_candidates,
    initialize_router_state,
)
from app.features.pipeline_ocr_router_execution import execute_router_candidates
from app.features.pipeline_ocr_router_output import (
    filter_corrected_blocks,
    finish_router_stage,
)
from app.features.pipeline_ocr_router_results import process_router_results
from app.features.pipeline_ocr_router_state import RouterStageState, resolve_router_port


async def run_ocr_router_stage(
    pipeline: Any,
    normalized_blocks: list[dict],
    options: dict,
    db: Any,
    keyword_arguments: dict,
    *,
    namespace: dict,
) -> dict:
    """Keep lazy construction, classification, gather, publication and flush in order."""
    from app.features.ocr_fix.metrics import OcrCorrectionMetrics
    from app.features.ocr_fix.router import OCRFixRouter

    state = RouterStageState(
        pipeline, normalized_blocks, options, db, keyword_arguments
    )
    ports = partial(resolve_router_port, namespace)
    state.router_config = await pipeline._build_router_config(options, db)
    state.router = OCRFixRouter()
    state.router.configure(state.router_config)
    state.page_images = keyword_arguments.get("page_images")
    state.metrics = OcrCorrectionMetrics()
    initialize_router_state(state, ports=ports)
    classify_router_candidates(state, ports=ports)
    await execute_router_candidates(state, ports=ports)
    process_router_results(state, ports=ports)
    filter_corrected_blocks(state, ports=ports)
    return finish_router_stage(state, ports=ports)
