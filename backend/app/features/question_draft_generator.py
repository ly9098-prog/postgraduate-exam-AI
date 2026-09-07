"""AI draft generation — generate question drafts via LLM.

Extracted from ``question_pipeline.py:generate_drafts`` (P5-3).
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import fallback
from app.ai.prompts import build_generate_questions

logger = logging.getLogger(__name__)


async def generate_drafts(
    db: AsyncSession,
    user_id: int,
    *,
    subject_code: str = "",
    knowledge_points: list[str],
    difficulty: int = 3,
    count: int = 3,
    question_type: str = "single_choice",
    extra_hint: str | None = None,
    subject_id: int | None = None,
) -> dict:
    """AI 批量生成草稿题目，进入暂存区。绝不直接进入正式题库。"""
    from app.features.question_pipeline import (
        SUBJECT_VALUES,
        TYPE_VALUES,
        _build_log,
        _call_or_fallback,
        _create_question_import,
        _extract_json,
        normalizer,
        process_question_pipeline,
    )

    # Resolve subject: prefer subject_id (DB lookup), fall back to subject string
    if subject_id:
        from app.models.admin import Subject
        subj = await db.get(Subject, subject_id)
        if not subj:
            raise ValueError(f"subject_id={subject_id} 不存在")
        subject_code = subj.code
    elif subject_code:
        if subject_code not in SUBJECT_VALUES:
            raise ValueError("subject_code 必须使用已注册的 canonical subject code")
    else:
        raise ValueError("必须提供 subject 或 subject_id")
    question_type = normalizer.normalize_type(question_type)
    if question_type not in TYPE_VALUES:
        raise ValueError(
            "question_type 仅支持 single_choice / multiple_choice / "
            "true_false / fill_blank / subjective"
        )
    count = max(1, min(10, count))

    batch_id = f"AIGEN_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    messages = build_generate_questions(
        subject_code, knowledge_points, difficulty, count, question_type, extra_hint
    )
    prompt_text = json.dumps(messages, ensure_ascii=False)
    resp, raw, _ = await _call_or_fallback(
        messages, fallback.get_fallback_generation(count), db
    )

    if raw is None:
        db.add(_build_log(
            user_id=user_id, action="generate", target_type="batch",
            target_id=None, batch_id=batch_id, prompt_text=prompt_text,
            raw_response=None, parsed_result=resp["fallback_value"],
            confidence=0.0,
            model=resp["model"], tokens_used=0, duration_ms=0,
            success=False, error_message=resp.get("error"),
        ))
        await db.commit()
        return {"batch_id": batch_id, "generated": 0, "from_fallback": True}

    parsed_raw = _extract_json(raw) or {}
    questions = parsed_raw.get("questions") if isinstance(parsed_raw, dict) else None
    if not isinstance(questions, list):
        questions = []

    generated = 0
    skipped_duplicate = 0
    for q in questions:
        if not isinstance(q, dict):
            continue
        result = process_question_pipeline(q, "ai")
        if not result["is_valid"]:
            continue
        norm = result["normalized"]
        qi = await _create_question_import(
            db,
            batch_id=batch_id,
            source_type="ai_generated",
            source_file=None,
            raw_data=q,
            result=result,
            extra_fields={
                "ai_generated": True,
                "ai_source": "generate",
                "subject_id": subject_id,
                "ai_metadata": {
                    "knowledge_points": norm["knowledge_points"],
                    "difficulty": norm["difficulty"],
                    "request": {
                        "subject": subject_code,
                        "knowledge_points": knowledge_points,
                        "difficulty": difficulty,
                        "question_type": question_type,
                    },
                },
                "ai_raw_response": raw,
                "ai_answer_flag": bool(result["import_fields"].get("parsed_answer")),
            },
            skip_existing=True,
        )
        if qi is None:
            skipped_duplicate += 1
            continue
        generated += 1

    db.add(_build_log(
        user_id=user_id, action="generate", target_type="batch",
        target_id=None, batch_id=batch_id, prompt_text=prompt_text,
        raw_response=raw, parsed_result={"count": generated, "skipped_duplicate": skipped_duplicate},
        confidence=None,
        model=resp["model"], tokens_used=resp["tokens_used"],
        duration_ms=resp["duration_ms"], success=True,
    ))
    await db.commit()
    return {
        "batch_id": batch_id,
        "generated": generated,
        "skipped_duplicate": skipped_duplicate,
        "from_fallback": False,
        "tokens_used": resp["tokens_used"],
        "duration_ms": resp["duration_ms"],
    }
