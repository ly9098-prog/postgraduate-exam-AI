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

from app.features.ai_safety import evaluate_and_trace, safe_accept_ai_result
from app.features.code_integrity import contains_code, detect_code_block_integrity
from app.features.pipeline_stages._helpers import _count_risk_flags
from app.features.token_budget import estimate_tokens, check_token_limit, record_token_usage

logger = logging.getLogger(__name__)

# Code integrity flags that trigger reconstruction
_CODE_STRUCTURE_FLAGS = frozenset({
    "code_brace_unbalanced",
    "code_block_incomplete",
    "code_block_truncated",
    "code_fence_unclosed",
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

    try:
        result = await deepseek.chat(
            messages,
            temperature=0.2,
            model=model_name,
            api_key=api_key,
            base_url=base_url,
        )
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
                try:
                    parsed = json.loads(content[start:end + 1])
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

        result = await _call_llm_for_structure_reconstruct(stem, config, db)

        if result is None:
            failed_count += 1
            fix_actions.append({
                "question_index": idx,
                "success": False,
                "reason": "llm_failed",
            })
            continue

        # Apply safety gate
        safety = evaluate_and_trace(
            stem_before,
            result["repaired_stem"],
            context={"is_code_context": True},
        )
        safety_check = safe_accept_ai_result(
            stem_before,
            result["repaired_stem"],
            context={"is_code_context": True},
        )

        if not safety_check.get("accepted", True):
            failed_count += 1
            logger.info(
                "Code structure safety gate rejected question %s: %s",
                q.get("number", idx),
                safety_check.get("rollback_reason", "unknown"),
            )
            fix_actions.append({
                "question_index": idx,
                "success": False,
                "reason": f"safety_rejected: {safety_check.get('rollback_reason', 'unknown')}",
            })
            continue

        # Apply the fix: update stem
        q["stem"] = result["repaired_stem"]
        reconstructed_count += 1

        # Remove resolved code integrity flags from risk_flags
        existing_flags = list(q.get("risk_flags") or [])
        for flag in _CODE_STRUCTURE_FLAGS:
            if flag in existing_flags:
                existing_flags.remove(flag)
        if existing_flags:
            q["risk_flags"] = existing_flags
        else:
            q.pop("risk_flags", None)

        # Update confidence_score if it was very low due to code issues
        current_conf = q.get("confidence_score", 0)
        if current_conf < 0.6:
            q["confidence_score"] = min(current_conf + 0.2, 0.6)

        # Add decision trace
        trace = list(q.get("decision_trace") or [])
        trace.append({
            "stage": "code_structure_reconstruct",
            "result": "repaired",
            "reason": ";".join(result.get("fix_actions", ["structure_fixed"])),
        })
        q["decision_trace"] = trace

        fix_actions.append({
            "question_index": idx,
            "success": True,
            "code_fixed": result.get("code_fixed", False),
            "confidence": result.get("confidence", 0.5),
            "tokens_used": result.get("token_used", 0),
            "actions": result.get("fix_actions", []),
        })

        logger.info(
            "Code structure reconstructed: q%s (code_fixed=%s, actions=%s)",
            q.get("number", idx),
            result.get("code_fixed"),
            result.get("fix_actions"),
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
