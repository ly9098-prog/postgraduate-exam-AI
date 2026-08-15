"""Eventually-consistent projections derived from a committed practice answer.

The HTTP transaction writes ``PracticeRecord`` + a transactional outbox row.
For wrong answers it also writes the user-visible ``WrongQuestion`` row
synchronously.  The queue worker later calls :func:`project_practice_answer`
for the remaining derived state.  ``AnswerBehavior.practice_record_id`` acts
as the durable processing receipt: if a Redis task is delivered again after the
DB commit but before queue acknowledgement, the whole event becomes a no-op.
"""
from __future__ import annotations

import logging

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.answer_behavior import AnswerBehavior
from app.models.practice_record import PracticeRecord
from app.models.question import Question
from app.models.wrong_question import WrongQuestion

logger = logging.getLogger(__name__)


async def project_practice_answer(
    db: AsyncSession,
    *,
    practice_record_id: int,
    request_id: str | None = None,
    wrong_question_projected: bool = False,
) -> dict:
    """Apply all answer-derived learning projections exactly once per record.

    The caller owns the transaction.  Any exception rolls back every projection
    so the durable queue can retry the complete event safely.
    """
    # Redis owner fencing prevents most duplicate workers, but a lease can
    # expire while a slow DB transaction is still running. PostgreSQL advisory
    # transaction locks serialize same-record projections without a schema
    # migration; SQLite/local development remains single-process best effort.
    bind = db.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        await db.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": int(practice_record_id)},
        )

    already_processed = await db.scalar(
        select(AnswerBehavior.id).where(
            AnswerBehavior.practice_record_id == practice_record_id
        ).limit(1)
    )
    if already_processed is not None:
        return {"processed": False, "duplicate": True, "wrong_question_id": None}

    row = await db.execute(
        select(PracticeRecord, Question)
        .join(Question, PracticeRecord.question_id == Question.id)
        .where(PracticeRecord.id == practice_record_id)
    )
    pair = row.first()
    if pair is None:
        # A task whose business record disappeared is not retryable: raising
        # would churn forever and eventually dead-letter a non-recoverable event.
        logger.warning("answer projection record missing: record_id=%s", practice_record_id)
        return {"processed": False, "missing": True, "wrong_question_id": None}

    record, question = pair
    user_id = int(record.user_id)
    question_id = int(record.question_id)
    is_correct = bool(record.is_correct)
    used_time = record.used_time
    user_answer = (record.user_answer or "").strip()

    wrong_question_id = None
    if not is_correct:
        # New submit paths persist WrongQuestion synchronously in the same
        # transaction as PracticeRecord so the wrong-book is immediately
        # consistent even when no scheduler/worker process is running.  Keep
        # this async path as a backward-compatible fallback for historical
        # outbox/reconciliation tasks, but never count the same wrong answer
        # twice when the synchronous projection already succeeded.
        wrong = None
        if wrong_question_projected:
            wrong = await db.scalar(
                select(WrongQuestion).where(
                    WrongQuestion.user_id == user_id,
                    WrongQuestion.question_id == question_id,
                    WrongQuestion.is_active,
                )
            )

        if wrong is None:
            from app.services.wrong_question_service import record_wrong

            wrong = await record_wrong(
                db,
                user_id,
                question_id,
                user_answer,
                commit=False,
            )
        wrong_question_id = wrong.id

    # Insert/update the idempotency receipt in the same transaction as every
    # other projection.  record_answer_behavior must not commit independently.
    from app.services.behavior_service import record_answer_behavior

    await record_answer_behavior(
        db=db,
        user_id=user_id,
        question_id=question_id,
        practice_record_id=record.id,
        time_spent_sec=used_time or 0,
        is_first_correct=is_correct,
        is_final_correct=is_correct,
        user_answer=user_answer,
        correct_answer=question.answer,
        subject_id=question.subject_id,
        session_type=record.mode or "practice",
        commit=False,
    )

    from app.services import mastery_service

    mastery_update = await mastery_service.update_user_knowledge_state_after_answer(
        db, user_id, question_id, is_correct, used_time=used_time,
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

    await db.commit()

    # Cache invalidation is deliberately after the DB transaction.  Stale cache
    # is recoverable/short-lived and must never roll back learning state.
    try:
        from app.services.vector_retrieval_service import invalidate_vector_cache

        await invalidate_vector_cache(user_id)
    except Exception:
        logger.debug("vector cache invalidation failed uid=%d", user_id, exc_info=True)

    # AI prewarm is a second asynchronous optimization.  It is safe to enqueue
    # only after the wrong-question projection is durable.
    if wrong_question_id is not None:
        try:
            from app.services.ai_prewarm_worker import enqueue_prewarm

            await enqueue_prewarm(wrong_question_id, user_id)
        except Exception:
            logger.warning(
                "AI prewarm enqueue failed after answer projection wq_id=%s uid=%s",
                wrong_question_id,
                user_id,
                exc_info=True,
            )

    return {
        "processed": True,
        "duplicate": False,
        "wrong_question_id": wrong_question_id,
    }
