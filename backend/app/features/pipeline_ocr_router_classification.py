"""Ordered classification and counters for OCR correction."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.features.pipeline_ocr_router_state import RouterStageState


def initialize_router_state(
    state: RouterStageState, *, ports: Callable[[str], Any]
) -> None:
    """Allocate stage counters before classification."""
    state.corrections = []
    state.corrected_blocks = [None] * ports("len")(state.normalized_blocks)
    state.stats = {
        "total_blocks": ports("len")(state.normalized_blocks),
        "noisy_blocks": 0,
        "corrected_blocks": 0,
        "skipped_blocks": 0,
        "model_used": "",
    }
    state.quality_gate_shadow_records = []
    state.model_call_totals = {
        "ai_calls": 0,
        "llm_calls": 0,
        "vl_calls": 0,
        "tokens_used": 0,
    }
    state.to_correct = []


def classify_router_candidates(
    state: RouterStageState, *, ports: Callable[[str], Any]
) -> None:
    """Classify every block before any budget or provider await."""
    for idx, block in ports("enumerate")(state.normalized_blocks):
        text = ports("str")(block.get("normalized_text") or "")
        if not text.strip():
            state.corrected_blocks[idx] = block
            continue
        noise_score = ports("_detect_noise")(block)
        structure_score = ports("_detect_structure_abnormal")(text)
        has_image = ports("bool")(state.page_images)
        should = ports("_should_correct")(
            noise_score,
            state.router_config,
            structure_score=structure_score,
            has_image=has_image,
        )
        if not should:
            state.corrected_blocks[idx] = block
            state.stats["skipped_blocks"] += 1
            state.corrections.append(
                {
                    "block_index": block.get("block_index", 0),
                    "page": block.get("page", 1),
                    "noise_score": ports("round")(noise_score, 3),
                    "structure_score": ports("round")(structure_score, 3),
                    "corrected": False,
                }
            )
            continue
        state.stats["noisy_blocks"] += 1
        state.to_correct.append((idx, block, text, noise_score, structure_score))
    state.metrics.record_classification(
        total=state.stats["total_blocks"],
        noisy=state.stats["noisy_blocks"],
        skipped=state.stats["skipped_blocks"],
    )
