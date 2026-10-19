"""AI 辅助导题 service。

所有 AI 输出仅写入 question_imports 暂存区，不直接进入 questions 正式表。
每次调用记录到 ai_generation_logs，便于追溯。
"""

import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import fallback
from app.ai.gateway import chat_with_db_model
from app.ai.prompts import (
    build_complete_question,
    build_enrich_question,
    build_generate_questions,
)
from app.models.ai_generation_log import AiGenerationLog
from app.models.question_import import QuestionImport
from app.services.ai_import_helpers import (
    SUBJECT_VALUES,
    TYPE_VALUES,
    detect_missing,
    extract_json,
    normalize_enrich,
    normalize_generated_question,
    qi_to_dict,
)


def _build_log(
    *,
    user_id: int,
    action: str,
    target_type: str | None,
    target_id: int | None,
    batch_id: str | None,
    prompt_text: str | None,
    raw_response: str | None,
    parsed_result: dict | None,
    confidence: float | None,
    model: str,
    tokens_used: int,
    duration_ms: int,
    success: bool,
    error_message: str | None = None,
) -> AiGenerationLog:
    return AiGenerationLog(
        user_id=user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        batch_id=batch_id,
        prompt_text=prompt_text,
        raw_response=raw_response,
        parsed_result=parsed_result,
        confidence=confidence,
        model=model,
        tokens_used=tokens_used,
        duration_ms=duration_ms,
        success=1 if success else 0,
        error_message=error_message,
    )


async def _call_or_fallback(
    db: AsyncSession,
    messages: list,
    fallback_value: dict,
) -> tuple[dict, str | None, dict | None]:
    """调用后台配置的 OpenAI-compatible 补全模型，失败则返回 fallback。"""
    try:
        resp = await chat_with_db_model(db, messages, feature="completion")
        if resp is None:
            raise RuntimeError("AI补全模型未配置")
        return (resp, resp["content"], resp)
    except (OSError, ValueError, RuntimeError, TimeoutError) as e:
        return (
            {
                "content": "",
                "tokens_used": 0,
                "model": "fallback",
                "duration_ms": 0,
                "fallback_value": fallback_value,
                "error": str(e),
            },
            None,
            None,
        )


async def enrich_import(db: AsyncSession, user_id: int, import_id: int) -> dict:
    """对单条 question_imports 记录补全 AI 字段。不覆盖人工已填写的字段。"""
    result = await db.execute(
        select(QuestionImport).where(QuestionImport.id == import_id)
    )
    qi: QuestionImport | None = result.scalar_one_or_none()
    if not qi:
        raise ValueError("导入记录不存在")
    if qi.status != "pending":
        raise ValueError("仅支持对 pending 记录使用 AI 辅助")

    messages = build_enrich_question(qi_to_dict(qi))
    prompt_text = json.dumps(messages, ensure_ascii=False)
    resp, raw, _ = await _call_or_fallback(db, messages, fallback.get_fallback_enrich())

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

    normalized = normalize_enrich(extract_json(raw) or {})
    if normalized.get("subject") and not qi.subject_id:
        from app.services.subject_resolution import resolve_subject_id

        resolved = await resolve_subject_id(db, normalized["subject"])
        if resolved is not None:
            qi.subject_id = resolved
    if normalized.get("question_type") and not qi.question_type:
        qi.question_type = normalized["question_type"]

    qi.ai_generated = True
    qi.ai_source = "enrich"
    qi.ai_confidence = normalized.get("confidence")
    qi.ai_metadata = normalized
    qi.ai_raw_response = raw

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
    db: AsyncSession, user_id: int, batch_id: str, limit: int = 50
) -> dict:
    """对批次中所有 pending 记录批量补全。逐条调用，避免单次过长。"""
    result = await db.execute(
        select(QuestionImport)
        .where(
            QuestionImport.batch_id == batch_id,
            QuestionImport.status == "pending",
        )
        .limit(limit)
    )
    records = list(result.scalars().all())
    if not records:
        return {"processed": 0, "succeeded": 0, "fallback": 0}

    succeeded = 0
    fallback_count = 0
    for qi in records:
        try:
            r = await enrich_import(db, user_id, qi.id)
        except ValueError:
            continue
        if r.get("from_fallback"):
            fallback_count += 1
        else:
            succeeded += 1
    return {
        "processed": len(records),
        "succeeded": succeeded,
        "fallback": fallback_count,
    }


async def generate_drafts(
    db: AsyncSession,
    user_id: int,
    *,
    subject_code: str,
    knowledge_points: list[str],
    difficulty: int = 3,
    count: int = 3,
    question_type: str = "choice",
    extra_hint: str | None = None,
) -> dict:
    """AI 批量生成题目草稿，统一进入 question_imports 暂存区。"""
    if subject_code not in SUBJECT_VALUES:
        raise ValueError("subject_code 必须使用已注册的 canonical subject code")
    if question_type not in TYPE_VALUES:
        raise ValueError("question_type 仅支持 choice / fill / subjective")
    count = max(1, min(10, count))

    from app.services.subject_resolution import resolve_subject_id

    resolved_subject_id = await resolve_subject_id(db, subject_code)
    if resolved_subject_id is None:
        raise ValueError(f"无法解析科目 code {subject_code!r} 到 subject_id")

    batch_id = (
        f"AIGEN_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    )
    messages = build_generate_questions(
        subject_code, knowledge_points, difficulty, count, question_type, extra_hint
    )
    prompt_text = json.dumps(messages, ensure_ascii=False)

    resp, raw, _ = await _call_or_fallback(
        db, messages, fallback.get_fallback_generation(count)
    )
    if raw is None:
        db.add(
            _build_log(
                user_id=user_id,
                action="generate",
                target_type="batch",
                target_id=None,
                batch_id=batch_id,
                prompt_text=prompt_text,
                raw_response=None,
                parsed_result=resp["fallback_value"],
                confidence=0.0,
                model=resp["model"],
                tokens_used=0,
                duration_ms=0,
                success=False,
                error_message=resp.get("error"),
            )
        )
        await db.commit()
        return {"batch_id": batch_id, "generated": 0, "from_fallback": True}

    parsed_raw = extract_json(raw) or {}
    questions = parsed_raw.get("questions") if isinstance(parsed_raw, dict) else None
    if not isinstance(questions, list):
        questions = []

    generated_count = 0
    for q in questions:
        norm = normalize_generated_question(q) if isinstance(q, dict) else None
        if not norm:
            continue
        db.add(
            QuestionImport(
                batch_id=batch_id,
                source_type="ai_generated",
                source_file=None,
                subject_id=resolved_subject_id,
                question_type=norm["question_type"],
                raw_data=q,
                parsed_content=norm["parsed_content"],
                parsed_options=norm["parsed_options"],
                parsed_answer=norm["parsed_answer"],
                parsed_analysis=norm["parsed_analysis"],
                status="pending",
                ai_generated=True,
                ai_source="generate",
                ai_metadata={
                    "knowledge_points": norm["knowledge_points"],
                    "difficulty": norm["difficulty"],
                    "request": {
                        "subject": subject_code,
                        "knowledge_points": knowledge_points,
                        "difficulty": difficulty,
                        "question_type": question_type,
                    },
                },
                ai_raw_response=raw,
                ai_answer_flag=bool(norm["parsed_answer"]),
            )
        )
        generated_count += 1

    db.add(
        _build_log(
            user_id=user_id,
            action="generate",
            target_type="batch",
            target_id=None,
            batch_id=batch_id,
            prompt_text=prompt_text,
            raw_response=raw,
            parsed_result={"count": generated_count},
            confidence=None,
            model=resp["model"],
            tokens_used=resp["tokens_used"],
            duration_ms=resp["duration_ms"],
            success=True,
        )
    )
    await db.commit()
    return {
        "batch_id": batch_id,
        "generated": generated_count,
        "from_fallback": False,
        "tokens_used": resp["tokens_used"],
        "duration_ms": resp["duration_ms"],
    }


async def complete_import(db: AsyncSession, user_id: int, import_id: int) -> dict:
    """AI 补全单条 import 记录的缺失字段。
    AI 给出的 answer 不会自动写入 parsed_answer，仅放在 ai_metadata 待人工确认。
    """
    result = await db.execute(
        select(QuestionImport).where(QuestionImport.id == import_id)
    )
    qi: QuestionImport | None = result.scalar_one_or_none()
    if not qi:
        raise ValueError("导入记录不存在")
    if qi.status != "pending":
        raise ValueError("仅支持对 pending 记录使用 AI 补全")

    missing = detect_missing(qi)
    if not missing:
        return {"missing": [], "from_fallback": False, "ai_metadata": {}}

    messages = build_complete_question(qi_to_dict(qi), missing)
    prompt_text = json.dumps(messages, ensure_ascii=False)
    resp, raw, _ = await _call_or_fallback(
        db, messages, fallback.get_fallback_complete(missing)
    )

    if raw is None:
        parsed = resp["fallback_value"]
        db.add(
            _build_log(
                user_id=user_id,
                action="complete",
                target_type="import",
                target_id=qi.id,
                batch_id=qi.batch_id,
                prompt_text=prompt_text,
                raw_response=None,
                parsed_result=parsed,
                confidence=0.0,
                model=resp["model"],
                tokens_used=0,
                duration_ms=0,
                success=False,
                error_message=resp.get("error"),
            )
        )
        await db.commit()
        return {"missing": missing, "from_fallback": True, "ai_metadata": parsed}

    parsed_raw = extract_json(raw) or {}
    suggestion = await _apply_complete_suggestion(qi, parsed_raw, missing, db=db)
    answer_uncertain = bool(parsed_raw.get("answer_uncertain"))
    confidence = _coerce_confidence(parsed_raw.get("confidence"))

    qi.ai_generated = True
    qi.ai_source = "complete"
    qi.ai_confidence = confidence
    qi.ai_metadata = {
        **(qi.ai_metadata or {}),
        "complete_suggestion": suggestion,
        "answer_uncertain": answer_uncertain,
        "reason": parsed_raw.get("reason"),
        "missing_fields": missing,
    }
    qi.ai_raw_response = raw

    db.add(
        _build_log(
            user_id=user_id,
            action="complete",
            target_type="import",
            target_id=qi.id,
            batch_id=qi.batch_id,
            prompt_text=prompt_text,
            raw_response=raw,
            parsed_result=qi.ai_metadata,
            confidence=confidence,
            model=resp["model"],
            tokens_used=resp["tokens_used"],
            duration_ms=resp["duration_ms"],
            success=True,
        )
    )
    await db.commit()
    return {
        "missing": missing,
        "from_fallback": False,
        "ai_metadata": qi.ai_metadata,
        "tokens_used": resp["tokens_used"],
        "duration_ms": resp["duration_ms"],
    }


def _coerce_confidence(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return max(0.0, min(1.0, float(value)))
    return None


async def _apply_complete_suggestion(
    qi: QuestionImport,
    parsed: dict,
    missing: list[str],
    db: AsyncSession | None = None,
) -> dict:
    """将 AI 补全结果有选择地写回 qi。answer 永远不直接写入 parsed_answer。"""
    suggestion: dict = {}
    if "subject_id" in missing and parsed.get("subject") in SUBJECT_VALUES:
        if db is not None:
            from app.services.subject_resolution import resolve_subject_id

            resolved = await resolve_subject_id(db, parsed["subject"])
        else:
            resolved = None
        if resolved is not None:
            qi.subject_id = resolved
            suggestion["subject_id"] = resolved
        else:
            suggestion["subject"] = parsed["subject"]
    if "question_type" in missing and parsed.get("question_type") in TYPE_VALUES:
        qi.question_type = parsed["question_type"]
        suggestion["question_type"] = parsed["question_type"]
    if "analysis" in missing:
        a = parsed.get("analysis")
        if isinstance(a, str) and a.strip():
            qi.parsed_analysis = a.strip()
            suggestion["analysis"] = a.strip()
    if "answer" in missing:
        ans = parsed.get("answer")
        if isinstance(ans, str) and ans.strip():
            suggestion["answer"] = ans.strip()
            qi.ai_answer_flag = True
    if isinstance(parsed.get("knowledge_points"), list):
        suggestion["knowledge_points"] = [
            str(k).strip() for k in parsed["knowledge_points"] if str(k).strip()
        ]
    if isinstance(parsed.get("difficulty"), (int, float)):
        suggestion["difficulty"] = max(1, min(5, int(parsed["difficulty"])))
    return suggestion


async def list_logs(
    db: AsyncSession,
    *,
    user_id: int | None = None,
    action: str | None = None,
    batch_id: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    conditions = []
    if user_id:
        conditions.append(AiGenerationLog.user_id == user_id)
    if action:
        conditions.append(AiGenerationLog.action == action)
    if batch_id:
        conditions.append(AiGenerationLog.batch_id == batch_id)

    stmt = select(AiGenerationLog)
    if conditions:
        stmt = stmt.where(*conditions)
    stmt = stmt.order_by(AiGenerationLog.id.desc())

    offset = (page - 1) * page_size
    items_res = await db.execute(stmt.offset(offset).limit(page_size))
    items = list(items_res.scalars().all())
    return {"items": items, "page": page, "pageSize": page_size}
