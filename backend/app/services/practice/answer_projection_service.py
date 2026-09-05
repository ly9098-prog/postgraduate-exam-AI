"""Project committed practice answers from immutable question revisions.

The projection worker treats ``practice_records`` as an explicit event contract,
not as a fully-hydrated ORM aggregate.  Only the columns required by the current
projection protocol are selected, and the terminal projection state is written
with an explicit UPDATE.  This keeps the worker decoupled from unrelated model
columns and makes schema changes fail at the contract boundary instead of being
silently pulled into a hot-path ``SELECT *``.

``PracticeRecord.question_version_id`` is the durable grading boundary.
``PracticeRecord.projection_state`` is the durable processing receipt;
reconciliation only repairs records explicitly left in ``pending``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin import QuestionVersion
from app.models.practice_record import PracticeRecord
from app.models.question import Question

logger = logging.getLogger(__name__)

PROJECTION_PENDING = "pending"
PROJECTION_COMPLETED = "completed"
PROJECTION_REVISION_ONLY = "revision_only"


@dataclass(frozen=True, slots=True)
class _ProjectionSource:
    id: int
    user_id: int
    question_id: int
    question_version_id: int | None
    subject_id: int
    user_answer: str
    is_correct: bool
    used_time: int | None
    answered_at: datetime
    mode: str | None
    projection_state: str


@dataclass(frozen=True, slots=True)
class _RevisionSource:
    id: int
    question_id: int
    subject_id: int | None
    answer: str | None


async def _lock_projection_source(
    db: AsyncSession,
    practice_record_id: int,
) -> _ProjectionSource | None:
    """Lock and load only the stable projection-event contract.

    A row lock is the single concurrency primitive for exactly-once projection.
    No advisory lock is needed: all projection work for an existing record is
    serialized by the same ``practice_records`` row until commit/rollback.
    """
    stmt = select(
        PracticeRecord.id,
        PracticeRecord.user_id,
        PracticeRecord.question_id,
        PracticeRecord.question_version_id,
        PracticeRecord.subject_id,
        PracticeRecord.user_answer,
        PracticeRecord.is_correct,
        PracticeRecord.used_time,
        PracticeRecord.answered_at,
        PracticeRecord.mode,
        PracticeRecord.projection_state,
    ).where(PracticeRecord.id == practice_record_id)

    bind = db.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update(of=PracticeRecord)

    row = (await db.execute(stmt)).mappings().one_or_none()
    if row is None:
        return None

    return _ProjectionSource(
        id=int(row["id"]),
        user_id=int(row["user_id"]),
        question_id=int(row["question_id"]),
        question_version_id=(
            int(row["question_version_id"])
            if row["question_version_id"] is not None
            else None
        ),
        subject_id=int(row["subject_id"]),
        user_answer=str(row["user_answer"] or ""),
        is_correct=bool(row["is_correct"]),
        used_time=int(row["used_time"]) if row["used_time"] is not None else None,
        answered_at=row["answered_at"],
        mode=str(row["mode"]) if row["mode"] is not None else None,
        projection_state=str(row["projection_state"]),
    )


async def _load_revision_source(
    db: AsyncSession,
    question_version_id: int,
) -> _RevisionSource | None:
    """Load the immutable revision fields consumed by projection."""
    row = (
        await db.execute(
            select(
                QuestionVersion.id,
                QuestionVersion.question_id,
                QuestionVersion.subject_id,
                QuestionVersion.answer,
            ).where(QuestionVersion.id == question_version_id)
        )
    ).mappings().one_or_none()
    if row is None:
        return None
    return _RevisionSource(
        id=int(row["id"]),
        question_id=int(row["question_id"]),
        subject_id=int(row["subject_id"]) if row["subject_id"] is not None else None,
        answer=str(row["answer"]) if row["answer"] is not None else None,
    )


async def _load_current_question_version(
    db: AsyncSession,
    question_id: int,
) -> int | None:
    """Read the mutable question's current revision id.

    Do not lock the question row here: projections for different users commonly
    target the same question and must remain parallel.  Immutable grading still
    comes exclusively from ``question_version_id``; this value only decides
    whether mutable review/adaptive state may be advanced.
    """
    value = await db.scalar(
        select(Question.current_version_id).where(Question.id == question_id)
    )
    return int(value) if value is not None else None


async def _finish_projection(
    db: AsyncSession,
    *,
    practice_record_id: int,
    target_state: str,
) -> None:
    """Move a locked pending record to its terminal projection state."""
    result = await db.execute(
        update(PracticeRecord)
        .where(
            PracticeRecord.id == practice_record_id,
            PracticeRecord.projection_state == PROJECTION_PENDING,
        )
        .values(projection_state=target_state)
    )
    if result.rowcount != 1:
        raise RuntimeError(
            "practice projection state transition lost ownership: "
            f"record_id={practice_record_id} target={target_state} rowcount={result.rowcount}"
        )


async def project_practice_answer(
    db: AsyncSession,
    *,
    practice_record_id: int,
    request_id: str | None = None,
) -> dict:
    """Apply answer-derived projections exactly once for one practice record.

    Revision-scoped projections (behavior + knowledge mastery + recommendation
    attribution) always use the immutable revision recorded with the answer.
    Mutable question-state projections (Leitner/adaptive state) are only applied
    when that revision is still the question's current revision.
    """
    record = await _lock_projection_source(db, practice_record_id)
    if record is None:
        logger.warning("answer projection record missing: record_id=%s", practice_record_id)
        return {"processed": False, "missing": True}

    if record.projection_state != PROJECTION_PENDING:
        return {
            "processed": False,
            "duplicate": True,
            "projection_state": record.projection_state,
        }
    if record.question_version_id is None:
        raise RuntimeError(
            f"practice record {practice_record_id} has no question_version_id"
        )

    revision = await _load_revision_source(db, record.question_version_id)
    if revision is None or revision.question_id != record.question_id:
        raise RuntimeError(
            f"practice record {practice_record_id} references invalid question revision"
        )

    current_version_id = await _load_current_question_version(db, record.question_id)
    is_current_revision = current_version_id == record.question_version_id

    user_id = record.user_id
    question_id = record.question_id
    is_correct = record.is_correct
    used_time = record.used_time
    user_answer = record.user_answer.strip()

    from app.services.behavior_service import record_answer_behavior

    await record_answer_behavior(
        db=db,
        user_id=user_id,
        question_id=question_id,
        practice_record_id=record.id,
        question_version_id=record.question_version_id,
        time_spent_sec=used_time or 0,
        is_first_correct=is_correct,
        is_final_correct=is_correct,
        user_answer=user_answer,
        correct_answer=revision.answer,
        subject_id=revision.subject_id or record.subject_id,
        session_type=record.mode or "practice",
        commit=False,
    )

    from app.services import mastery_service

    mastery_update = await mastery_service.update_user_knowledge_state_after_answer(
        db,
        user_id,
        question_id,
        is_correct,
        used_time=used_time,
        question_version_id=record.question_version_id,
    )

    from app.services import recommendation_log_service

    await recommendation_log_service.mark_recommendation_answered(
        db,
        user_id,
        question_id,
        is_correct,
        request_id=request_id,
        mastery_after=(mastery_update or {}).get("mastery_after"),
        mastery_delta=(mastery_update or {}).get("mastery_delta"),
    )

    if is_current_revision:
        from app.services import question_review_service

        review_transition = await question_review_service.update_user_question_state_after_answer(
            db,
            user_id,
            question_id,
            is_correct,
            used_time=used_time,
            answered_at=record.answered_at,
        )

        from app.services import adaptive_learning_service

        await adaptive_learning_service.update_adaptive_state_after_answer(
            db,
            user_id=user_id,
            question_id=question_id,
            is_correct=is_correct,
            answer_time_seconds=used_time,
            answered_at=record.answered_at,
            is_due_review=review_transition.is_due_review,
            is_overdue_review=review_transition.is_overdue_review,
        )
        target_state = PROJECTION_COMPLETED
    else:
        # Revision-scoped evidence is still valid, but mutable question state
        # belongs to the newer revision and must not be changed by this answer.
        target_state = PROJECTION_REVISION_ONLY

    await _finish_projection(
        db,
        practice_record_id=record.id,
        target_state=target_state,
    )
    await db.commit()

    try:
        from app.services.vector_retrieval_service import invalidate_vector_cache

        await invalidate_vector_cache(user_id)
    except Exception:
        logger.debug("vector cache invalidation failed uid=%d", user_id, exc_info=True)

    return {
        "processed": True,
        "duplicate": False,
        "projection_state": target_state,
        "question_version_id": record.question_version_id,
    }
