"""Project committed practice answers from immutable question revisions.

``PracticeRecord.question_version_id`` is the durable grading boundary.  A
projection must never re-interpret an answer through the mutable ``Question``
row.  ``PracticeRecord.projection_state`` is the durable processing receipt;
reconciliation only repairs records explicitly left in ``pending``.
"""
from __future__ import annotations

import logging

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin import QuestionVersion
from app.models.practice_record import PracticeRecord
from app.models.question import Question

logger = logging.getLogger(__name__)

PROJECTION_PENDING = "pending"
PROJECTION_COMPLETED = "completed"
PROJECTION_REVISION_ONLY = "revision_only"


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
    bind = db.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        await db.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": int(practice_record_id)},
        )

    query = (
        select(PracticeRecord)
        .where(PracticeRecord.id == practice_record_id)
    )
    if bind is not None and bind.dialect.name == "postgresql":
        query = query.with_for_update()
    record = await db.scalar(query)
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
        # Post-migration records must always bind an immutable revision.  Keep
        # the row pending so observability/reconciliation exposes the data issue
        # instead of silently projecting against mutable question state.
        raise RuntimeError(
            f"practice record {practice_record_id} has no question_version_id"
        )

    revision = await db.scalar(
        select(QuestionVersion).where(QuestionVersion.id == record.question_version_id)
    )
    if revision is None or int(revision.question_id) != int(record.question_id):
        raise RuntimeError(
            f"practice record {practice_record_id} references invalid question revision"
        )

    current_version_id = await db.scalar(
        select(Question.current_version_id).where(Question.id == record.question_id)
    )
    is_current_revision = (
        current_version_id is not None
        and int(current_version_id) == int(record.question_version_id)
    )

    user_id = int(record.user_id)
    question_id = int(record.question_id)
    is_correct = bool(record.is_correct)
    used_time = record.used_time
    user_answer = (record.user_answer or "").strip()

    from app.services.behavior_service import record_answer_behavior

    await record_answer_behavior(
        db=db,
        user_id=user_id,
        question_id=question_id,
        practice_record_id=record.id,
        question_version_id=int(record.question_version_id),
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
        question_version_id=int(record.question_version_id),
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
        record.projection_state = PROJECTION_COMPLETED
    else:
        # The answer still updates revision-scoped knowledge evidence, but it
        # must not mutate the scheduling/state machine of a different revision.
        record.projection_state = PROJECTION_REVISION_ONLY

    await db.commit()

    try:
        from app.services.vector_retrieval_service import invalidate_vector_cache

        await invalidate_vector_cache(user_id)
    except Exception:
        logger.debug("vector cache invalidation failed uid=%d", user_id, exc_info=True)

    return {
        "processed": True,
        "duplicate": False,
        "projection_state": record.projection_state,
        "question_version_id": int(record.question_version_id),
    }
