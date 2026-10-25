"""Persist wrong-book/diagnosis side effects for an evaluated practice batch."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def persist_wrong_answer(
    db: AsyncSession,
    *,
    user_id: int,
    record: Any,
    question: Any,
    wrong: Any,
    now: datetime,
) -> dict:
    from app.services import error_diagnosis_service

    diagnosis = await error_diagnosis_service.record_error_event(
        db,
        user_id=user_id,
        wrong_question_id=int(wrong.id),
        question_id=int(question.id),
        question_version_id=int(question.question_version_id),
        practice_record_id=int(record.id),
        source_context="practice",
        user_answer=record.user_answer,
        occurred_at=record.answered_at or now,
        queue_ai=False,
    )
    return error_diagnosis_service.serialize_diagnosis(diagnosis)


async def enqueue_wrong_answer_prewarm(
    wrong_questions: list[Any],
    user_id: int,
    *,
    build_revision: Callable[..., dict],
    enqueue: Callable[..., Awaitable[Any]],
) -> None:
    """Best-effort AI prewarm after the practice transaction has committed."""
    for wrong in wrong_questions:
        revision = build_revision(
            review_count=wrong.review_count,
            wrong_answer=wrong.wrong_answer,
        )
        await enqueue(wrong.id, user_id, revision=revision)
