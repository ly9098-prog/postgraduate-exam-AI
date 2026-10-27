"""Transactional side-effect persistence for an evaluated practice batch."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.practice_record import PracticeRecord


@dataclass(slots=True)
class PersistedPracticeBatch:
    records: list[tuple[Any, Any, bool, str, int | None]]
    prewarm_wrong_questions: list[Any]
    wrong_question_ids: dict[int, int]


def _build_practice_record(
    *,
    user_id: int,
    q: Any,
    is_correct: bool,
    user_answer: str,
    used_time: int | None,
    mode: str,
    now: datetime,
) -> PracticeRecord:
    return PracticeRecord(
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


async def _stage_practice_batch_records(
    db: AsyncSession,
    *,
    user_id: int,
    evaluated_answers: list[tuple[Any, bool, str, int | None]],
    mode: str,
    now: datetime,
) -> list[tuple[Any, Any, bool, str, int | None]]:
    records: list[tuple[Any, Any, bool, str, int | None]] = []
    for q, is_correct, user_answer, used_time in evaluated_answers:
        record = _build_practice_record(
            user_id=user_id,
            q=q,
            is_correct=is_correct,
            user_answer=user_answer,
            used_time=used_time,
            mode=mode,
            now=now,
        )
        db.add(record)
        records.append((record, q, is_correct, user_answer, used_time))
    if records:
        await db.flush()
    return records


async def _persist_practice_wrong_record(
    db: AsyncSession,
    *,
    user_id: int,
    record: Any,
    q: Any,
    user_answer: str,
    now: datetime,
    record_wrong: Callable[..., Awaitable[Any]],
    persist_wrong_answer: Callable[..., Awaitable[dict]],
) -> tuple[Any, dict]:
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
    return wrong, diagnosis_payload


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
    records = await _stage_practice_batch_records(
        db,
        user_id=user_id,
        evaluated_answers=evaluated_answers,
        mode=mode,
        now=now,
    )

    prewarm_wrong_questions: list[Any] = []
    wrong_question_ids: dict[int, int] = {}
    for record, q, is_correct, user_answer, _used_time in records:
        if not is_correct:
            wrong, diagnosis_payload = await _persist_practice_wrong_record(
                db,
                user_id=user_id,
                record=record,
                q=q,
                user_answer=user_answer,
                now=now,
                record_wrong=record_wrong,
                persist_wrong_answer=persist_wrong_answer,
            )
            prewarm_wrong_questions.append(wrong)
            wrong_question_ids[int(q.id)] = int(wrong.id)
            setattr(record, "_error_diagnosis_payload", diagnosis_payload)
        await create_outbox(
            db,
            practice_record_id=int(record.id),
            request_id=answer_request_ids.get(int(q.id)),
        )
    return PersistedPracticeBatch(records, prewarm_wrong_questions, wrong_question_ids)
