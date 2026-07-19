"""AI edit trace & safety gate — delegates all acceptance decisions to CandidateEvaluator.

Each AI intervention point records a unified trace. The ``safe_accept_ai_result``
function is now a thin compatibility adapter that delegates to
``CandidateEvaluator`` and converts the result back to the legacy dict format.

All callers (pipeline_orchestrator, ai_repair, ocr_correction, code_structure_stage)
continue to work without changes.

AIEditTrace now at app.core.ai_trace (re-exported here for backward compat).
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.ai_trace import AIEditTrace  # noqa: F401 — re-export

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# safe_accept_ai_result — delegates to CandidateEvaluator
# ---------------------------------------------------------------------------


def safe_accept_ai_result(
    before: str,
    after: str,
    *,
    context: dict[str, Any] | None = None,
    quality_report: dict[str, Any] | None = None,
) -> dict:
    """Multi-dimensional AI edit audit — delegates to CandidateEvaluator.

    Returns (legacy dict format for backward compat)::

        {
            "accepted": bool,
            "risk_flags": [str],
            "rollback_reason": str | None,
            "diff": str,
        }
    """
    from app.features.candidate_evaluator import CandidateDecision, evaluate_candidate

    evaluation = evaluate_candidate(
        before, after,
        context=context,
        quality_report=quality_report,
        provenance={"source": "ai_safety.safe_accept_ai_result"},
    )

    accepted = evaluation.decision == CandidateDecision.ACCEPT
    return {
        "accepted": accepted,
        "risk_flags": evaluation.risk_flags,
        "rollback_reason": None if accepted else evaluation.reason_code,
        "diff": evaluation.diff,
    }


# ---------------------------------------------------------------------------
# evaluate_and_trace
# ---------------------------------------------------------------------------


def evaluate_and_trace(
    stage: str,
    model: str,
    before: str,
    after: str,
    *,
    context: dict[str, Any] | None = None,
    quality_report: dict[str, Any] | None = None,
    tokens_used: int = 0,
    duration_ms: int = 0,
) -> tuple[AIEditTrace, str]:
    """Evaluate AI edit and return (trace, final_text).

    If rejected, ``final_text == before`` (rollback to original).
    """
    safety = safe_accept_ai_result(
        before, after,
        context=context,
        quality_report=quality_report,
    )

    trace = AIEditTrace(
        stage=stage,
        model=model,
        before=before[:2000],
        after=after[:2000],
        diff=safety["diff"],
        risk_flags=safety["risk_flags"],
        accepted=safety["accepted"],
        rollback_reason=safety["rollback_reason"],
        tokens_used=tokens_used,
        duration_ms=duration_ms,
        context=context or {},
    )

    if not safety["accepted"]:
        logger.warning(
            "AI safety REJECTED [%s/%s]: %s",
            stage, model, safety["rollback_reason"],
        )
        return trace, before  # rollback

    if safety["risk_flags"]:
        logger.info(
            "AI safety ACCEPTED with flags [%s/%s]: %s",
            stage, model, ", ".join(safety["risk_flags"]),
        )

    return trace, after
