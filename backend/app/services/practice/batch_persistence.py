"""Transactional side-effect persistence for an evaluated practice batch."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.practice_record import PracticeRecord



@dataclass(slots=True)
class PersistedPracticeBatch:
    records: list[tuple[Any, Any, bool, str, int | None]]
    prewarm_wrong_questions: list[Any]
    wrong_question_ids: dict[int, int]


async def persist_practice_batch_records(
    db: AsyncSession,
    *,
    user_id: int,
    evaluated_answers: list[tuple[Any, bool, str, int | None]],
    answer_request_ids: dict[int, str | None],
    mode: str,
    now: datetime,
    record_wrong: Callable[..., Awaitable[Any]],
    create_outbox: Callable[..., Awaitable[Any]],
    persist_wrong_answer: Callable[..., Awaitable[dict]],
) -> PersistedPracticeBatch:
    records: list[tuple[Any, Any, bool, str, int | None]] = []
    for q, is_correct, user_answer, used_time in evaluated_answers:
        record = PracticeRecord(
            user_id=user_id,
            question_id=int(q.id),
            question_version_id=int(q.question_version_id),
            subject_id=int(q.subject_id),
            question_type=q.question_type,
            user_answer=user_answer,
            is_correct=is_correct,
            used_time=used_time,
            answered_at=now,
            mode=mode,
            projection_state="pending",
        )
        db.add(record)
        records.append((record, q, is_correct, user_answer, used_time))
    if records:
        await db.flush()

    prewarm_wrong_questions: list[Any] = []
    wrong_question_ids: dict[int, int] = {}
    for record, q, is_correct, user_answer, _used_time in records:
        if not is_correct:
            wrong = await record_wrong(
                db,
                user_id,
                int(q.id),
                user_answer,
                question_version_id=int(q.question_version_id),
                commit=False,
            )
            diagnosis_payload = await persist_wrong_answer(
                db,
                user_id=user_id,
                record=record,
                question=q,
                wrong=wrong,
                now=now,
            )
            prewarm_wrong_questions.append(wrong)
            wrong_question_ids[int(q.id)] = int(wrong.id)
            setattr(record, "_error_diagnosis_payload", diagnosis_payload)
        await create_outbox(
            db,
            practice_record_id=int(record.id),
            request_id=answer_request_ids.get(int(q.id)),
        )
    return PersistedPracticeBatch(
        records, prewarm_wrong_questions, wrong_question_ids
    )
