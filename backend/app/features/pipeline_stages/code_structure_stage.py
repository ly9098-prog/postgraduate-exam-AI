"""Code structure reconstruction stage — fix unbalanced braces, indentation, OCR symbol errors.

Sits between ``normalize_schema`` and ``classify_questions`` (before AI repair).
Only triggers for questions with code integrity flags (code_brace_unbalanced,
code_block_incomplete, code_fence_unclosed). Uses the LLM with a focused
code-structure-only prompt.

Design:
- Stage input: questions (list[dict]) from normalize_schema
- Only processes questions with code integrity flags
- Calls LLM with code_structure_reconstruct prompt to fix the stem
- Uses AI safety gate to validate the fix
- Stage output: questions with fixed stems + updated risk_flags
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.features.candidate_evaluator import CandidateDecision, CandidateEvaluator
from app.features.code_integrity import contains_code, detect_code_block_integrity
from app.features.pipeline_stages._helpers import _count_risk_flags
from app.features.token_budget import check_token_limit, estimate_tokens, record_token_usage

logger = logging.getLogger(__name__)

# Confidence boost applied to reconstructed questions
_CONFIDENCE_BUMP = 0.2
_CONFIDENCE_CAP = 0.6

# Code integrity flags that trigger reconstruction
_CODE_STRUCTURE_FLAGS = frozenset({
    "code_brace_unbalanced",
    "code_block_incomplete",
    "code_block_truncated",
    "code_fence_unclosed",
    "code_garbled_text",
    "code_line_break_suspicious",
})


def _questions_with_code_issues(questions: list[dict]) -> list[tuple[int, dict]]:
    """Return (index, question) pairs where stem has code structure issues.

    Checks both risk_flags and direct stem integrity scan to catch
    cases where flags haven't been synced yet.
    """
    candidates: list[tuple[int, dict]] = []
    for i, q in enumerate(questions):
        stem = q.get("stem", "")
        if not stem:
            continue
        if not contains_code(stem):
            continue

        # Check risk_flags first (fast path)
        risk_flags = set(q.get("risk_flags") or [])
        if risk_flags & _CODE_STRUCTURE_FLAGS:
            candidates.append((i, q))
            continue

        # Double-check via integrity scan (catch unsynced flags)
        integrity = detect_code_block_integrity(stem)
        if integrity["flags"]:
            # Sync flags to question so downstream can see them
            existing = list(q.get("risk_flags") or [])
            for f in integrity["flags"]:
                if f not in existing:
                    existing.append(f)
            q["risk_flags"] = existing
            candidates.append((i, q))

    return candidates


async def _call_llm_for_structure_reconstruct(
    stem: str,
    config: dict,
    db: Any = None,
) -> dict | None:
    """Call LLM to reconstruct code structure in the stem.

    Returns: {"repaired_stem": str, "code_fixed": bool, "confidence": float, "token_used": int}
             or None on failure/overshoot.
    """
    from app.ai.client import deepseek
    from app.ai.prompts import build_code_structure_reconstruct

    # Resolve credentials if db is available
    api_key = None
    base_url = None
    model_name = None
    if db is not None:
        from app.services.model_config_resolver import ensure_db_model_configured
        creds = await ensure_db_model_configured(db)
        if creds:
            api_key = creds[0]
            base_url = creds[1]
            model_name = creds[2]

    messages = build_code_structure_reconstruct(stem)
    prompt_text = json.dumps(messages, ensure_ascii=False)
    estimated = estimate_tokens(prompt_text)

    if not await check_token_limit(estimated, config):
        logger.warning("Token limit exceeded for code structure reconstruction")
        return None

    kwargs = dict(messages=messages, temperature=0.2, api_key=api_key, base_url=base_url)
    if model_name:
        kwargs["model"] = model_name
    try:
        result = await deepseek.chat(**kwargs)
    except Exception as e:
        logger.warning("Code structure LLM call failed: %s", e)
        return None

    await record_token_usage(result["tokens_used"])

    content = result["content"].strip()
    # Parse JSON from response
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        # Try extracting from ```json block
        import re
        m = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", content)
        if m:
            try:
                parsed = json.loads(m.group(1))
            except json.JSONDecodeError:
                return None
        else:
            # Fallback: try to extract top-level {...}
            start = content.find("{")
            end = content.rfind("}")
            if start >= 0 and end > start:
                candidate = content[start:end + 1]
                # Quick sanity check: must start with {"stem" to avoid
                # picking up unrelated braces (e.g. from C code in output)
                stripped = candidate.lstrip()
                if not stripped.startswith('{"stem"'):
                    return None
                try:
                    parsed = json.loads(candidate)
                except json.JSONDecodeError:
                    return None
            else:
                return None

    repaired_stem = parsed.get("stem", "").strip()
    if not repaired_stem:
        return None

    return {
        "repaired_stem": repaired_stem,
        "code_fixed": parsed.get("code_fixed", False),
        "confidence": parsed.get("confidence", 0.5),
        "token_used": result["tokens_used"],
        "fix_actions": parsed.get("fix_actions", []),
    }


async def run_code_structure_stage(
    questions: list[dict],
    options: dict | None = None,
    *,
    db: Any = None,
) -> dict:
    """Run code structure reconstruction for questions with code integrity issues.

    Args:
        questions: Questions from normalize_schema stage.
        options: Pipeline options dict.
        db: Optional DB session for model config resolution.

    Returns:
        dict with ``questions``, ``reconstructed_count``, ``warnings``, etc.
    """
    opts = options or {}
    enable_reconstruct = opts.get("enable_code_structure_reconstruct", True)
    if not enable_reconstruct or not questions:
        return {
            "questions": questions,
            "reconstructed_count": 0,
            "failed_count": 0,
            "warnings": [],
            "fix_actions": [],
        }

    config = {
        "daily_token_limit": opts.get("daily_token_limit", 100000),
        "monthly_token_limit": opts.get("monthly_token_limit", 2000000),
    }

    # Find questions with code structure issues
    candidates = _questions_with_code_issues(questions)
    if not candidates:
        return {
            "questions": questions,
            "reconstructed_count": 0,
            "failed_count": 0,
            "warnings": [],
            "fix_actions": [],
        }

    logger.info(
        "Code structure reconstruction: %d candidate(s) found",
        len(candidates),
    )

    reconstructed_count = 0
    failed_count = 0
    fix_actions: list[dict] = []
    warnings: list[str] = []

    for idx, q in candidates:
        stem = q.get("stem", "")
        stem_before = stem

        # Capture pre-reconstruction code integrity flags (P0: prevent false success)
        _pre_integrity = detect_code_block_integrity(stem)
        _pre_flags = set(_pre_integrity.get("flags", []))
        _pre_score = _pre_integrity.get("score", 0)

        result = await _call_llm_for_structure_reconstruct(stem, config, db)

        if result is None:
            failed_count += 1
            fix_actions.append({
                "question_index": idx,
                "success": False,
                "reason": "llm_failed",
            })
            continue

        # Apply safety gate via CandidateEvaluator (unified single acceptance authority)
        evaluator = CandidateEvaluator()
        evaluation = evaluator.evaluate(
            original_text=stem_before,
            candidate_text=result["repaired_stem"],
            context={"is_code_context": True},
            provenance={"stage": "code_structure_reconstruct", "model": "deepseek"},
        )

        if evaluation.decision != CandidateDecision.ACCEPT:
            failed_count += 1
            logger.info(
                "Code structure safety gate rejected question %s: %s",
                q.get("number", idx),
                evaluation.reason_code or "unknown",
            )
            fix_actions.append({
                "question_index": idx,
                "success": False,
                "reason": f"safety_rejected: {evaluation.reason_code or 'unknown'}",
            })
            continue

        # Apply the fix: update stem with accepted text from evaluator
        q["stem"] = evaluation.accepted_text

        # ── P0: Post-reconstruction integrity validation ──
        # Run integrity check on the new stem to see which flags were actually resolved.
        # Don't trust the LLM's self-reported confidence — rule-based detection is authoritative.
        _post_integrity = detect_code_block_integrity(evaluation.accepted_text)
        _post_flags = set(_post_integrity.get("flags", []))
        _post_score = _post_integrity.get("score", 0)

        # Compute resolved flags (present in pre but absent in post)
        _resolved_flags = _pre_flags - _post_flags
        # Compute flags that persist (present in both)
        _persisted_flags = _pre_flags & _post_flags

        # Only remove flags that were actually resolved
        existing_flags = list(q.get("risk_flags") or [])
        for flag in _resolved_flags:
            while flag in existing_flags:
                existing_flags.remove(flag)
        # Re-add any persisted flags that might have been removed by mistake
        for flag in _persisted_flags:
            if flag not in existing_flags:
                existing_flags.append(flag)
        if existing_flags:
            q["risk_flags"] = existing_flags
        else:
            q.pop("risk_flags", None)

        # Only count as reconstructed if at least one flag was actually resolved
        if _resolved_flags and _post_score < _pre_score:
            reconstructed_count += 1
        else:
            failed_count += 1
            logger.info(
                "Code structure reconstruction had no measurable improvement for q%s: "
                "pre_flags=%s post_flags=%s pre_score=%.2f post_score=%.2f",
                q.get("number", idx),
                sorted(_pre_flags), sorted(_post_flags),
                _pre_score, _post_score,
            )
            fix_actions.append({
                "question_index": idx,
                "success": False,
                "reason": "integrity_not_improved",
                "pre_flags": sorted(_pre_flags),
                "post_flags": sorted(_post_flags),
                "pre_score": _pre_score,
                "post_score": _post_score,
            })
            continue

        # Only boost confidence if no garbled text persists
        if "code_garbled_text" not in _persisted_flags:
            current_conf = q.get("confidence_score", 0)
            if current_conf < _CONFIDENCE_CAP:
                q["confidence_score"] = min(current_conf + _CONFIDENCE_BUMP, _CONFIDENCE_CAP)

        # Add decision trace
        dt = list(q.get("decision_trace") or [])
        dt.append({
            "stage": "code_structure_reconstruct",
            "result": "repaired",
            "reason": ";".join(result.get("fix_actions", ["structure_fixed"])),
        })
        q["decision_trace"] = dt

        fix_actions.append({
            "question_index": idx,
            "success": True,
            "code_fixed": len(_resolved_flags) > 0,
            "confidence": result.get("confidence", 0.5),
            "tokens_used": result.get("token_used", 0),
            "actions": result.get("fix_actions", []),
            "pre_flags": sorted(_pre_flags),
            "post_flags": sorted(_post_flags),
            "resolved_flags": sorted(_resolved_flags),
        })

        logger.info(
            "Code structure reconstructed: q%s (resolved=%s, persisted=%s, pre_score=%.2f post_score=%.2f)",
            q.get("number", idx),
            sorted(_resolved_flags),
            sorted(_persisted_flags),
            _pre_score, _post_score,
        )

    if reconstructed_count:
        warnings.append(
            f"code_structure: reconstructed {reconstructed_count} question(s)"
        )
    if failed_count:
        warnings.append(
            f"code_structure: {failed_count} question(s) failed reconstruction"
        )

    return {
        "questions": questions,
        "reconstructed_count": reconstructed_count,
        "failed_count": failed_count,
        "warnings": warnings,
        "fix_actions": fix_actions,
        "risk_flag_counts": _count_risk_flags(questions),
    }
