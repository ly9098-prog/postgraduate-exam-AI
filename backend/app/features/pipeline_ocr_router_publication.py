"""Safety trace and accepted/rejected OCR candidate publication."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.features.pipeline_ocr_router_state import RouterCandidate, RouterStageState


def publish_accepted_candidate(
    state: RouterStageState, candidate: RouterCandidate, *, ports: Callable[[str], Any]
) -> None:
    """Publish accepted text, correction counters, logging and metrics."""
    candidate.new_block["normalized_text"] = candidate.safe_text
    candidate.new_block["ocr_correction_applied"] = True
    candidate.new_block["ocr_fix_model"] = candidate.result.model_used
    state.stats["corrected_blocks"] += 1
    ports("logger").info(
        "【OCR-5】AI纠错输出 | block=%d page=%d model=%s conf=%.2f\n  └─ 纠错前: %.160s\n  └─ 纠错后: %.160s",
        candidate.idx,
        candidate.block.get("page", 1),
        candidate.result.model_used,
        candidate.result.confidence,
        candidate.text,
        candidate.safe_text,
    )
    state.metrics.record_correction(
        model=candidate.result.model_used,
        before=candidate.text,
        after=candidate.safe_text,
        duration_ms=ports("getattr")(candidate.result, "duration_ms", None),
        tokens=candidate.result.tokens_used,
    )
    state.corrections.append(
        {
            "block_index": candidate.block.get("block_index", 0),
            "page": candidate.block.get("page", 1),
            "noise_score": ports("round")(candidate.noise_score, 3),
            "structure_score": ports("round")(candidate.structure_score, 3),
            "corrected": True,
            "model_used": candidate.result.model_used,
            "before_preview": ports("_safe_text_summary")(candidate.text),
            "after_preview": ports("_safe_text_summary")(candidate.safe_text),
            "safety": candidate.safety_dict,
        }
    )


def publish_rejected_candidate(
    state: RouterStageState, candidate: RouterCandidate, *, ports: Callable[[str], Any]
) -> None:
    """Keep original text when the safety evaluator rejects a candidate."""
    ports("logger").warning(
        "【OCR-5-SAFETY】纠错被拒绝 | block=%d reason=%s",
        candidate.idx,
        candidate.reason_code,
    )
    state.corrections.append(
        {
            "block_index": candidate.block.get("block_index", 0),
            "page": candidate.block.get("page", 1),
            "noise_score": ports("round")(candidate.noise_score, 3),
            "structure_score": ports("round")(candidate.structure_score, 3),
            "corrected": False,
            "reason": f"safety_rejected: {candidate.reason_code}",
            "model_used": candidate.result.model_used,
            "before_preview": ports("_safe_text_summary")(candidate.text),
            "safety": candidate.safety_dict,
        }
    )


def publish_evaluation(
    state: RouterStageState,
    candidate: RouterCandidate,
    decision_type: Any,
    *,
    ports: Callable[[str], Any],
) -> None:
    """Build the compatibility trace before accept/reject projection."""
    candidate.accepted = candidate.evaluation.decision == decision_type.ACCEPT
    candidate.safe_text = candidate.evaluation.accepted_text or candidate.text
    candidate.reason_code = candidate.evaluation.reason_code
    candidate.risk_flags = candidate.evaluation.risk_flags
    candidate.diff = candidate.evaluation.diff
    candidate.safety_dict = {
        "stage": "ocr_fix",
        "model": candidate.result.model_used,
        "before": candidate.text[:500],
        "after": candidate.safe_text[:500],
        "diff": candidate.diff,
        "risk_flags": candidate.risk_flags,
        "accepted": candidate.accepted,
        "rollback_reason": candidate.reason_code if not candidate.accepted else None,
        "tokens_used": candidate.result.tokens_used or 0,
        "duration_ms": ports("getattr")(candidate.result, "duration_ms", None) or 0,
    }
    if candidate.accepted:
        publish_accepted_candidate(state, candidate, ports=ports)
    else:
        publish_rejected_candidate(state, candidate, ports=ports)
