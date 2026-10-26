"""Domain quality observations at the original failure boundary."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.features.pipeline_ocr_router_state import RouterCandidate, RouterStageState


def observe_domain_quality(
    state: RouterStageState, candidate: RouterCandidate, *, ports: Callable[[str], Any]
) -> None:
    """Record shadow/enforce observations without replacing the evaluator decision."""
    if ports("_get_domain_quality_gate_mode")() in ("shadow", "enforce"):
        try:
            from app.features.quality_gate import CompositeQualityGate
            from app.features.quality_gate import QualityContext as QGateContext
            from app.features.quality_gate import (
                record_shadow_decision as _record_qgate,
            )

            _qgate = CompositeQualityGate()
            _qctx = QGateContext(
                pipeline_fingerprint=state.pipeline.pipeline_id or "ocr_correction",
                gate_mode=ports("_get_domain_quality_gate_mode")(),
                existing_decision="accept",
                doc_ir_source=candidate.result.model_used or "unknown",
            )
            _qdecisions = _qgate.evaluate(
                candidate.text, candidate.result.fixed_text, _qctx
            )
            for _qd in _qdecisions:
                entry = _record_qgate(_qd, _qctx)
                entry["candidate_index"] = candidate.idx
                entry["page"] = candidate.block.get("page", 1)
                state.quality_gate_shadow_records.append(entry)
        except ports("Exception") as _qexc:
            ports("logger").warning(
                "[QUALITY-GATE] shadow evaluation failed: %s", _qexc
            )
