"""AI repair stage — repair low-confidence questions + validate results.

Extracted from ``pipeline_orchestrator.py:_run_repair`` and
``_run_ai_validation`` (P5-2).
"""

from __future__ import annotations

import logging

from app.features.ai_repair import repair_questions
from app.features.ai_validation import validate_ai_results
from app.features.pipeline_stages._helpers import (
    _count_risk_flags,
    _log_multi_blank_stage,
)

logger = logging.getLogger(__name__)


def _build_repair_diffs(
    repaired: list[dict], unrepaired: list[dict], skipped: list[dict],
) -> list[dict]:
    """Build per-question repair diff records for diagnostics stage_diffs."""
    diffs: list[dict] = []
    for r in repaired:
        before = r.get("before") or {}
        after = r.get("after") or {}
        safety = r.get("safety") or {}
        diffs.append({
            "question_index": r.get("question_index"),
            "actions": r.get("repair_actions", []),
            "confidence": r.get("confidence"),
            "tokens_used": r.get("token_used", 0),
            "before_stem": str(before.get("stem", ""))[:200],
            "after_stem": str(after.get("stem", ""))[:200],
            "options_changed": (
                str(before.get("options", "")) != str(after.get("options", ""))
            ),
            "answer_changed": (
                str(before.get("answer", "")) != str(after.get("answer", ""))
            ),
            "safety": safety,
        })
    for u in unrepaired:
        diffs.append({
            "question_index": u.get("question_index"),
            "actions": [],
            "reason": u.get("reason", "unrepaired"),
        })
    for s in skipped:
        diffs.append({
            "question_index": s.get("question_index"),
            "actions": [],
            "reason": s.get("reason", "skipped"),
        })
    return diffs




def should_send_to_llm(code_integrity_score: float) -> bool:
    """Pre-filter gate to decide if a question should be sent to LLM repair.

    Rule:
    - code_integrity_score < 0.6 → rule-based only (don't send to LLM)
    - code_integrity_score >= 0.6 → allow LLM repair

    Args:
        code_integrity_score: Code integrity score (0.0-1.0, higher = more intact).

    Returns:
        True if the question should be sent to LLM repair.
    """
    return code_integrity_score >= 0.6


async def run_repair_stage(
    questions: list[dict],
    options: dict,
    *,
    db=None,
    batch_validation_diagnostics: dict | None = None,
) -> dict:
    """AI repair for low-confidence questions.

    Questions flagged as batch duplicates are skipped to save tokens.

    Returns:
        dict with ``questions``, ``repaired_count``, ``unrepaired_count``,
        ``skipped_count``, ``total_tokens``, ``risk_flag_counts``,
        ``warnings``, ``repair_diffs``, ``repair_stats`` keys.
    """
    # Separate batch duplicates from repair candidates
    to_repair: list[dict] = []
    duplicate_indices: set[int] = set()
    for i, q in enumerate(questions):
        if q.get("is_batch_duplicate"):
            duplicate_indices.add(i)
        else:
            to_repair.append(q)

    repair_config = {
        "confidence_threshold": options.get("confidence_threshold", 0.6),
        "high_confidence_threshold": options.get("high_confidence_threshold", 0.95),
        "daily_token_limit": options.get("daily_token_limit", 100000),
        "monthly_token_limit": options.get("monthly_token_limit", 2000000),
        "enabled": options.get("enable_ai_repair", True),
        "low_risk_skip_enabled": options.get("enable_low_risk_skip", True),
    }
    roman_anomalies = (batch_validation_diagnostics or {}).get("roman_anomalies", [])
    result = await repair_questions(
        to_repair, repair_config, db=db,
        roman_diagnostics=roman_anomalies,
    )

    repaired = result.get("repaired", [])
    unrepaired = result.get("unrepaired", [])
    skipped = result.get("skipped", [])
    stats = result.get("stats", {})

    # Build the combined question list
    repaired_combined: list[dict] = [None] * len(to_repair)  # type: ignore

    for r in repaired:
        idx = r["question_index"]
        repaired_combined[idx] = r["after"]

    for u in unrepaired:
        idx = u["question_index"]
        repaired_combined[idx] = to_repair[idx]

    for s in skipped:
        idx = s["question_index"]
        original = dict(to_repair[idx])
        if s.get("reason") == "non_question_like":
            flags = list(original.get("risk_flags") or [])
            flags.append("non_question_like")
            original["risk_flags"] = list(dict.fromkeys(flags))
        elif s.get("reason") == "low_risk_high_confidence":
            original["repair_skipped"] = True
            original["repair_skipped_reason"] = "low_risk_high_confidence"
        repaired_combined[idx] = original

    repaired_combined = [q for q in repaired_combined if q is not None]

    # Merge back: non-duplicates (repaired) + duplicates (unchanged)
    combined: list[dict] = []
    repair_iter = iter(repaired_combined)
    for i, q in enumerate(questions):
        if i in duplicate_indices:
            combined.append(q)
        else:
            combined.append(next(repair_iter))
    _log_multi_blank_stage("repair", combined)

    warnings: list[str] = []
    if duplicate_indices:
        warnings.append(f"{len(duplicate_indices)} batch duplicates skipped repair")
    if unrepaired:
        warnings.append(f"{len(unrepaired)} questions unrepaired by AI")
    if skipped:
        reason_counts: dict[str, int] = {}
        for s in skipped:
            reason = str(s.get("reason") or "unknown")
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
        if reason_counts == {"above_threshold": len(skipped)}:
            warnings.append(f"{len(skipped)} questions skipped (above threshold)")
        else:
            reason_summary = ", ".join(
                f"{reason}={count}" for reason, count in sorted(reason_counts.items())
            )
            warnings.append(f"{len(skipped)} questions skipped repair ({reason_summary})")

    # Repair stats
    repair_total = len(to_repair)
    repair_skipped = len(skipped)
    repair_called = len(repaired)
    skip_rate = round(repair_skipped / repair_total, 4) if repair_total > 0 else 0.0
    if repaired:
        avg_tokens_per_repair = int(round(
            sum(r.get("token_used", 0) for r in repaired) / len(repaired)
        ))
        estimated_tokens_saved = avg_tokens_per_repair * repair_skipped
    else:
        avg_tokens_per_repair = 0
        estimated_tokens_saved = 0
    repair_stats = {
        "repair_total": repair_total,
        "repair_skipped": repair_skipped,
        "repair_called": repair_called,
        "skip_rate": skip_rate,
        "estimated_tokens_saved": estimated_tokens_saved,
        "avg_tokens_per_repair": avg_tokens_per_repair,
    }

    return {
        "questions": combined,
        "repaired_count": len(repaired),
        "unrepaired_count": len(unrepaired),
        "skipped_count": len(skipped),
        "total_tokens": stats.get("total_tokens", 0),
        "risk_flag_counts": _count_risk_flags(combined),
        "warnings": warnings,
        "repair_diffs": _build_repair_diffs(repaired, unrepaired, skipped),
        "repair_stats": repair_stats,
    }


def run_ai_validation_stage(questions: list[dict]) -> dict:
    """Validate AI repair results for anomalies."""
    result = validate_ai_results(questions)

    stats = result["stats"]
    warnings: list[str] = []
    if stats["errors"] > 0:
        warnings.append(f"{stats['errors']} questions have AI validation errors")
    if stats["warnings"] > 0:
        warnings.append(f"{stats['warnings']} questions have AI validation warnings")

    return {
        "questions": result["questions"],
        "ai_validation_diagnostics": stats,
        "warnings": warnings,
    }
