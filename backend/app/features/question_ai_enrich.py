"""AI enrich — enrich pending question imports with AI-generated metadata.

Extracted from ``question_pipeline.py:enrich_import, enrich_batch`` (P5-3).
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import fallback
from app.ai.client import llm
from app.ai.gateway import resolve_llm_runtime_config
from app.ai.prompts import build_enrich_question
from app.features.question_ai_complete import _has_complete_answer_risk
from app.features.question_pipeline import (
    SUBJECT_VALUES,
    _build_log,
    _call_or_fallback,
    _extract_json,
    _get_qi,
    _qi_to_dict,
)

logger = logging.getLogger(__name__)


def _normalize_enrich(parsed: dict) -> dict:
    """Normalize AI enrich response into structured metadata."""
    out: dict = {}
    # Prefer subject_id (int) from AI; fall back to legacy subject string
    sid = parsed.get("subject_id")
    if isinstance(sid, int) and sid > 0:
        out["subject_id"] = sid
    else:
        subject_code = parsed.get("subject")
        if subject_code in SUBJECT_VALUES:
            # Keep legacy string for caller to resolve to subject_id
            out["subject"] = subject_code
    qtype = parsed.get("question_type")
    from app.features.question_pipeline import normalizer

    normalized_type = normalizer.normalize_type(qtype)
    if normalized_type:
        out["question_type"] = normalized_type
    diff = parsed.get("difficulty")
    if isinstance(diff, (int, float)):
        diff = int(diff)
        if 1 <= diff <= 5:
            out["difficulty"] = diff
    kps = parsed.get("knowledge_points")
    if isinstance(kps, list):
        out["knowledge_points"] = [str(k).strip() for k in kps if str(k).strip()]
    chapter = parsed.get("chapter")
    if isinstance(chapter, str) and chapter.strip():
        out["chapter"] = chapter.strip()
    cat = parsed.get("question_category")
    if isinstance(cat, str) and cat.strip():
        out["question_category"] = cat.strip()
    conf = parsed.get("confidence")
    if isinstance(conf, (int, float)):
        out["confidence"] = max(0.0, min(1.0, float(conf)))
    reason = parsed.get("reason")
    if isinstance(reason, str):
        out["reason"] = reason
    return out


async def enrich_import(db: AsyncSession, user_id: int, import_id: int) -> dict:
    """AI 丰富单题信息（科目、题型、难度、知识点等）。"""
    qi = await _get_qi(db, import_id)
    if qi.status != "pending":
        raise ValueError("仅支持对 pending 记录使用 AI 辅助")

    # P3-5: check if complete stage changed answer — if so, skip enrich
    qi_meta = qi.ai_metadata or {}
    if _has_complete_answer_risk(qi_meta):
        logger.warning(
            "P3-5: enrich_import %d skipped — complete changed answer (risk)",
            import_id,
        )
        qi.ai_metadata = {
            **qi_meta,
            "_enrich_skipped_reason": "complete_high_risk",
            "_enrich_risk_flags": ["enrich_skipped_due_to_complete_risk"],
        }
        await db.commit()
        return {
            "from_fallback": False,
            "ai_metadata": qi.ai_metadata,
            "skipped_reason": "complete_high_risk",
        }

    messages = build_enrich_question(_qi_to_dict(qi))
    prompt_text = json.dumps(messages, ensure_ascii=False)
    resp, raw, _ = await _call_or_fallback(messages, fallback.get_fallback_enrich(), db)

    if raw is None:
        parsed = resp["fallback_value"]
        db.add(
            _build_log(
                user_id=user_id,
                action="enrich",
                target_type="import",
                target_id=qi.id,
                batch_id=qi.batch_id,
                prompt_text=prompt_text,
                raw_response=None,
                parsed_result=parsed,
                confidence=parsed.get("confidence"),
                model=resp["model"],
                tokens_used=0,
                duration_ms=0,
                success=False,
                error_message=resp.get("error"),
            )
        )
        await db.commit()
        return {"from_fallback": True, "ai_metadata": parsed}

    normalized = _normalize_enrich(_extract_json(raw) or {})
    # Apply subject_id (direct or resolve legacy subject string)
    if not qi.subject_id:
        if normalized.get("subject_id"):
            qi.subject_id = normalized["subject_id"]
        elif normalized.get("subject"):
            from app.services.subject_resolution import resolve_subject_id

            resolved = await resolve_subject_id(db, normalized["subject"])
            if resolved is not None:
                qi.subject_id = resolved
                normalized["subject_id"] = resolved
                normalized.pop("subject", None)
            else:
                logger.warning(
                    "enrich: resolve_subject_id failed for subject=%r, import_id=%d",
                    normalized["subject"],
                    qi.id,
                )
    if normalized.get("question_type") and not qi.question_type:
        qi.question_type = normalized["question_type"]
    qi.ai_generated = True
    qi.ai_source = "enrich"
    qi.ai_confidence = normalized.get("confidence")
    qi.ai_metadata = normalized
    qi.ai_raw_response = raw

    # 记录 AI enrich trace
    from app.core.ai_trace import AIEditTrace

    enrich_trace = AIEditTrace(
        stage="ai_enrich",
        model=resp.get("model", "unknown"),
        before=str(_qi_to_dict(qi))[:500],
        after=str(normalized)[:500],
        tokens_used=resp.get("tokens_used", 0),
        duration_ms=resp.get("duration_ms", 0),
    )
    if qi.ai_metadata is None:
        qi.ai_metadata = {}
    qi.ai_metadata["_trace"] = enrich_trace.to_dict()

    db.add(
        _build_log(
            user_id=user_id,
            action="enrich",
            target_type="import",
            target_id=qi.id,
            batch_id=qi.batch_id,
            prompt_text=prompt_text,
            raw_response=raw,
            parsed_result=normalized,
            confidence=normalized.get("confidence"),
            model=resp["model"],
            tokens_used=resp["tokens_used"],
            duration_ms=resp["duration_ms"],
            success=True,
        )
    )
    await db.commit()
    return {
        "from_fallback": False,
        "ai_metadata": normalized,
        "tokens_used": resp["tokens_used"],
        "duration_ms": resp["duration_ms"],
    }


async def enrich_batch(
    db: AsyncSession,
    user_id: int,
    batch_id: str,
    limit: int = 50,
    max_concurrency: int = 3,
) -> dict:
    """批量 AI 丰富。分三阶段：顺序预读 → 并发 LLM → 顺序落 DB。"""
    _start_time = datetime.now()
    from sqlalchemy import select

    from app.models.question_import import QuestionImport

    res = await db.execute(
        select(QuestionImport)
        .where(
            QuestionImport.batch_id == batch_id,
            QuestionImport.status == "pending",
        )
        .limit(limit)
    )
    records = list(res.scalars().all())
    if not records:
        return {"processed": 0, "succeeded": 0, "fallback": 0}

    # 预读 OpenAI-compatible 模型配置（仅一次，避免并发阶段访问 DB）
    runtime = await resolve_llm_runtime_config(db, feature="completion")

    # P3-5: skip enrich for questions with high-risk complete
    skipped_count = 0

    # Phase 1: 顺序预读所有 QI，构建 Prompt
    prepared: list[dict] = []
    for qi in records:
        if _has_complete_answer_risk(qi.ai_metadata or {}):
            logger.warning(
                "P3-5: enrich_batch skip import_id=%d — complete changed answer",
                qi.id,
            )
            qi.ai_metadata = dict(qi.ai_metadata or {})
            qi.ai_metadata["_enrich_skipped_reason"] = "complete_high_risk"
            qi.ai_metadata["_enrich_risk_flags"] = [
                "enrich_skipped_due_to_complete_risk"
            ]
            skipped_count += 1
            continue

        messages = build_enrich_question(_qi_to_dict(qi))
        prompt_text = json.dumps(messages, ensure_ascii=False)
        prepared.append(
            {
                "qi": qi,
                "messages": messages,
                "prompt_text": prompt_text,
                "fallback_value": fallback.get_fallback_enrich(),
            }
        )

    # Phase 2: 并发调用 AI（纯 HTTP，无 DB 操作）
    sem = asyncio.Semaphore(max_concurrency)

    async def _call(item: dict) -> dict:
        async with sem:
            if runtime is None:
                item["error"] = "AI模型API Key未配置"
                return item
            from app.core.config import settings
            from app.features.token_budget import check_token_limit, estimate_tokens

            _estimated = (
                estimate_tokens(json.dumps(item["messages"], ensure_ascii=False)) * 3
            )
            if not await check_token_limit(
                _estimated,
                {
                    "daily_token_limit": settings.AI_DAILY_TOKEN_LIMIT,
                    "monthly_token_limit": settings.AI_MONTHLY_TOKEN_LIMIT,
                },
            ):
                item["error"] = "token_budget_exhausted"
                return item
            try:
                resp = await llm.chat(
                    item["messages"],
                    model=runtime.model_name,
                    api_key=runtime.api_key,
                    base_url=runtime.base_url,
                    provider=runtime.provider,
                )
                item["resp"] = resp
                item["raw"] = resp["content"]
            except Exception as e:
                item["error"] = str(e)
            return item

    gathered = await asyncio.gather(
        *[_call(item) for item in prepared],
        return_exceptions=True,
    )

    # Phase 3: 顺序应用结果到 DB
    succeeded = 0
    fallback_count = 0

    for result in gathered:
        if not isinstance(result, dict):
            fallback_count += 1
            continue

        item = result
        qi = item["qi"]

        if "raw" not in item or item["raw"] is None:
            parsed = item["fallback_value"]
            db.add(
                _build_log(
                    user_id=user_id,
                    action="enrich",
                    target_type="import",
                    target_id=qi.id,
                    batch_id=qi.batch_id,
                    prompt_text=item["prompt_text"],
                    raw_response=None,
                    parsed_result=parsed,
                    confidence=parsed.get("confidence"),
                    model="fallback",
                    tokens_used=0,
                    duration_ms=0,
                    success=False,
                    error_message=item.get("error"),
                )
            )
            fallback_count += 1
            continue

        resp = item["resp"]
        raw = item["raw"]
        normalized = _normalize_enrich(_extract_json(raw) or {})
        # Apply subject_id (direct or resolve legacy subject string)
        if not qi.subject_id:
            if normalized.get("subject_id"):
                qi.subject_id = normalized["subject_id"]
            elif normalized.get("subject"):
                from app.services.subject_resolution import resolve_subject_id

                resolved = await resolve_subject_id(db, normalized["subject"])
                if resolved is not None:
                    qi.subject_id = resolved
                    normalized["subject_id"] = resolved
                    normalized.pop("subject", None)
                else:
                    logger.warning(
                        "enrich_batch: resolve_subject_id failed for subject=%r, import_id=%d",
                        normalized["subject"],
                        qi.id,
                    )
        if normalized.get("question_type") and not qi.question_type:
            qi.question_type = normalized["question_type"]
        qi.ai_generated = True
        qi.ai_source = "enrich"
        qi.ai_confidence = normalized.get("confidence")
        qi.ai_metadata = normalized
        qi.ai_raw_response = raw

        from app.core.ai_trace import AIEditTrace

        enrich_trace = AIEditTrace(
            stage="ai_enrich",
            model=resp.get("model", "unknown"),
            before=str(_qi_to_dict(qi))[:500],
            after=str(normalized)[:500],
            tokens_used=resp.get("tokens_used", 0),
            duration_ms=resp.get("duration_ms", 0),
        )
        if qi.ai_metadata is None:
            qi.ai_metadata = {}
        qi.ai_metadata["_trace"] = enrich_trace.to_dict()

        db.add(
            _build_log(
                user_id=user_id,
                action="enrich",
                target_type="import",
                target_id=qi.id,
                batch_id=qi.batch_id,
                prompt_text=item["prompt_text"],
                raw_response=raw,
                parsed_result=normalized,
                confidence=normalized.get("confidence"),
                model=resp["model"],
                tokens_used=resp["tokens_used"],
                duration_ms=resp["duration_ms"],
                success=True,
            )
        )
        succeeded += 1

    total_enrich_tokens = sum(
        (result.get("resp") or {}).get("tokens_used", 0)
        for result in gathered
        if isinstance(result, dict) and result.get("resp")
    )
    if total_enrich_tokens:
        from app.features.token_budget import record_token_usage

        await record_token_usage(total_enrich_tokens)

    _duration_ms = int((datetime.now() - _start_time).total_seconds() * 1000)

    await db.commit()
    return {
        "processed": len(records),
        "succeeded": succeeded,
        "fallback": fallback_count,
        "skipped_complete_risk": skipped_count,
        "enrich_stats": {
            "total": len(records),
            "success": succeeded,
            "failed": fallback_count,
            "skipped": skipped_count,
            "concurrency": max_concurrency,
            "duration_ms": _duration_ms,
            "tokens_used": total_enrich_tokens,
        },
    }
