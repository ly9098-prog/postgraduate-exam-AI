"""Persist accepted or repaired AI error-analysis results."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.answer_grounding import merge_grounded_diagnosis
from app.ai.prompts import AI_ANALYSIS_PROMPT_VERSION
from app.models.ai_chat import AiChat
from app.models.wrong_question import WrongQuestion


async def persist_repaired_analysis(
    db: AsyncSession,
    *,
    wrong_question: WrongQuestion,
    user_id: int,
    context: dict,
    result: dict,
    answer_grounding: dict,
    visual_evidence: str,
    visual_ack_retried: bool,
    visual_ack_retry_ms: int,
    image_count: int,
    input_signature: str,
    model_signature: str,
    expected_answer_check: Any,
    grounding_guard_reason: str,
    actual_answer_check: Any,
    tokens_used: int,
    duration_ms: int,
    effective_force: bool,
    runtime: Any,
) -> tuple[dict, str]:
    from app.ai.answer_grounding import build_safe_grounded_analysis

    safe = build_safe_grounded_analysis(answer_grounding)
    generated_at = datetime.now(UTC).isoformat()
    safe["_meta"] = _base_meta(
        model="grounding_guard",
        source_model=result.get("model", ""),
        runtime=runtime,
        generated_at=generated_at,
        force_regenerated=effective_force,
        visual_evidence=visual_evidence,
        visual_ack_retried=visual_ack_retried,
        visual_ack_retry_ms=visual_ack_retry_ms,
        image_count=image_count,
        input_signature=input_signature,
        model_signature=model_signature,
        expected_answer_check=expected_answer_check,
    )
    safe["_meta"]["grounding_guard"] = "repaired"
    safe["_meta"]["grounding_guard_reason"] = grounding_guard_reason
    wrong_question.ai_analysis = safe
    await db.commit()

    snapshot = build_context_snapshot(
        context,
        image_count=image_count,
        visual_evidence=visual_evidence,
        visual_ack_retried=visual_ack_retried,
        visual_ack_retry_ms=visual_ack_retry_ms,
    )
    snapshot["grounding_guard"] = {
        "status": "repaired",
        "reason": grounding_guard_reason,
        "expected_answer_check": expected_answer_check,
        "actual_answer_check": actual_answer_check,
    }
    await _append_analysis_chat(
        db,
        user_id=user_id,
        context=context,
        result=result,
        snapshot=snapshot,
        tokens_used=tokens_used,
        duration_ms=duration_ms,
    )
    return safe, generated_at


async def persist_valid_analysis(
    db: AsyncSession,
    *,
    wrong_question: WrongQuestion,
    user_id: int,
    context: dict,
    result: dict,
    parsed: dict,
    answer_grounding: dict,
    visual_evidence: str,
    visual_ack_retried: bool,
    visual_ack_retry_ms: int,
    image_count: int,
    input_signature: str,
    model_signature: str,
    expected_answer_check: Any,
    effective_force: bool,
    tokens_used: int,
    duration_ms: int,
    runtime: Any,
) -> str:
    parsed["mistake_diagnosis"] = merge_grounded_diagnosis(
        answer_grounding, parsed.get("mistake_diagnosis", "")
    )
    parsed["_meta"] = _base_meta(
        model=result.get("model", ""),
        source_model="",
        runtime=runtime,
        generated_at=datetime.now(UTC).isoformat(),
        force_regenerated=effective_force,
        visual_evidence=visual_evidence,
        visual_ack_retried=visual_ack_retried,
        visual_ack_retry_ms=visual_ack_retry_ms,
        image_count=image_count,
        input_signature=input_signature,
        model_signature=model_signature,
        expected_answer_check=expected_answer_check,
    )
    parsed["_meta"]["grounding_guard"] = "passed"
    wrong_question.ai_analysis = parsed
    await db.commit()

    snapshot = build_context_snapshot(
        context,
        image_count=image_count,
        visual_evidence=visual_evidence,
        visual_ack_retried=visual_ack_retried,
        visual_ack_retry_ms=visual_ack_retry_ms,
    )
    await _append_analysis_chat(
        db,
        user_id=user_id,
        context=context,
        result=result,
        snapshot=snapshot,
        tokens_used=tokens_used,
        duration_ms=duration_ms,
    )
    return str(parsed["_meta"]["generated_at"])


def build_context_snapshot(
    context: dict,
    *,
    image_count: int,
    visual_evidence: str,
    visual_ack_retried: bool,
    visual_ack_retry_ms: int,
) -> dict:
    snapshot = dict(context)
    snapshot["visual_input_count"] = image_count
    snapshot["visual_evidence"] = visual_evidence or None
    snapshot["visual_ack_retried"] = visual_ack_retried
    snapshot["visual_ack_retry_ms"] = visual_ack_retry_ms
    return snapshot


def _base_meta(
    *,
    model: str,
    source_model: str,
    runtime: Any,
    generated_at: str,
    force_regenerated: bool,
    visual_evidence: str,
    visual_ack_retried: bool,
    visual_ack_retry_ms: int,
    image_count: int,
    input_signature: str,
    model_signature: str,
    expected_answer_check: Any,
) -> dict:
    meta = {
        "model": model,
        "provider": runtime.provider,
        "model_config_id": runtime.model_config_id,
        "generated_at": generated_at,
        "version": AI_ANALYSIS_PROMPT_VERSION,
        "from_fallback": False,
        "force_regenerated": force_regenerated,
        "visual_input_count": image_count,
        "visual_evidence": visual_evidence or None,
        "visual_ack_retried": visual_ack_retried,
        "visual_ack_retry_ms": visual_ack_retry_ms,
        "input_mode": "vision" if image_count else "text",
        "input_signature": input_signature,
        "model_signature": model_signature,
        "answer_check": expected_answer_check,
    }
    if source_model:
        meta["source_model"] = source_model
    return meta


async def _append_analysis_chat(
    db: AsyncSession,
    *,
    user_id: int,
    context: dict,
    result: dict,
    snapshot: dict,
    tokens_used: int,
    duration_ms: int,
) -> None:
    # Never persist base64 image payloads in chat logs/context snapshots.
    db.add(
        AiChat(
            user_id=user_id,
            session_type="error_analysis",
            user_message=str(context["question"]),
            ai_response=result.get("content", ""),
            context_snapshot=snapshot,
            tokens_used=tokens_used,
            model=result.get("model", ""),
            duration_ms=duration_ms,
        )
    )
    await db.commit()
