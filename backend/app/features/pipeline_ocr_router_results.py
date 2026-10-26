"""Safety evaluation and ordered correction result processing."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.features.pipeline_ocr_router_candidates import (
    project_candidate_metadata,
    record_failed_candidate,
    record_unchanged_candidate,
)
from app.features.pipeline_ocr_router_publication import publish_evaluation
from app.features.pipeline_ocr_router_quality import observe_domain_quality
from app.features.pipeline_ocr_router_state import RouterCandidate, RouterStageState


def evaluate_router_candidate(
    state: RouterStageState, candidate: RouterCandidate, *, ports: Callable[[str], Any]
) -> None:
    """Evaluate eligible text, observe quality and publish with the captured decision enum."""
    from app.features.candidate_evaluator import CandidateDecision, get_evaluator

    if candidate.is_vl and (not candidate.result.confidence):
        ports("logger").info(
            "VL result submitted to safety gate (conf=0.0, text_len=%d)",
            ports("len")(candidate.result.fixed_text),
        )
    candidate.evaluation = get_evaluator().evaluate(
        original_text=candidate.text,
        candidate_text=candidate.result.fixed_text,
        context={
            "has_options": ports("bool")(
                ports("re").search("[A-D][.、．）)\\s]", candidate.text)
            ),
            "stem_context": candidate.text[:200],
        },
        quality_report={
            "low_confidence": candidate.noise_score > 0.3,
            "garbled_detected": candidate.structure_score > 0.2,
        },
        provenance={
            "engine": candidate.result.model_used or "",
            "model_version": candidate.result.model_used or "",
        },
    )
    observe_domain_quality(state, candidate, ports=ports)
    publish_evaluation(state, candidate, ports=ports, decision_type=CandidateDecision)


def process_router_candidate(
    state: RouterStageState, candidate: RouterCandidate, *, ports: Callable[[str], Any]
) -> None:
    """Process results in input order after all model tasks have settled."""
    if ports("isinstance")(candidate.fix_result, ports("BaseException")):
        record_failed_candidate(state, candidate, ports=ports)
        return
    project_candidate_metadata(state, candidate, ports=ports)
    if candidate.result.fixed_text != candidate.text and (
        candidate.result.confidence
        and candidate.result.confidence > 0
        or candidate.is_vl
    ):
        evaluate_router_candidate(state, candidate, ports=ports)
    else:
        record_unchanged_candidate(state, candidate, ports=ports)
    state.corrected_blocks[candidate.idx] = candidate.new_block


def process_router_results(
    state: RouterStageState, *, ports: Callable[[str], Any]
) -> None:
    """Retain gather order and original exception/cancellation child semantics."""
    for (idx, block, text, noise_score, structure_score), fix_result in ports("zip")(
        state.to_correct, state.fix_results
    ):
        candidate = RouterCandidate(
            idx, block, text, noise_score, structure_score, fix_result
        )
        process_router_candidate(state, candidate, ports=ports)
