"""Strict sequential-practice progress.

This module is intentionally isolated from recommendation/Leitner code.  A
sequential session means deterministic coverage of one leaf subject; learning
state may be updated after answers, but it never changes which question is next.
"""
from __future__ import annotations

import logging
from datetime import datetime
from uuid import uuid4

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.time_utils import utcnow
from app.features.question_type import (
    QT_MULTI_BLANK_CHOICE,
    QT_MULTIPLE_CHOICE,
    QT_SINGLE_CHOICE,
    QT_TRUE_FALSE,
)
from app.models.practice_record import PracticeRecord
from app.models.practice_session import PracticeSession
from app.models.question import Question
from app.services.knowledge_point_service import kp_exact_conditions
from app.services.question_revision_service import (
    latest_question_revision_scope_condition,
)

logger = logging.getLogger(__name__)

SEQUENTIAL_MODE = "sequential"
SEQUENTIAL_RESET_MODE = "sequential_reset"
SEQUENTIAL_RESET_STATUS = "marker"

# Keep sequential mode aligned with the controls provided by quiz-runner.
# Free-text/subjective revisions remain in the bank but are not issuable here.
SEQUENTIAL_ANSWERABLE_QUESTION_TYPES = frozenset({
    QT_SINGLE_CHOICE,
    QT_MULTIPLE_CHOICE,
    QT_TRUE_FALSE,
    QT_MULTI_BLANK_CHOICE,
})


async def _get_reset_at(
    db: AsyncSession, *, user_id: int, subject_id: int,
) -> datetime | None:
    return await db.scalar(
        select(func.max(PracticeSession.finished_at)).where(
            PracticeSession.user_id == user_id,
            PracticeSession.subject_id == subject_id,
            PracticeSession.mode == SEQUENTIAL_RESET_MODE,
            PracticeSession.status == SEQUENTIAL_RESET_STATUS,
        )
    )


def _answered_ids_query(*, user_id: int, subject_id: int, reset_at: datetime | None):
    query = select(PracticeRecord.question_id).where(
        PracticeRecord.user_id == user_id,
        PracticeRecord.subject_id == subject_id,
        PracticeRecord.mode == SEQUENTIAL_MODE,
    )
    if reset_at is not None:
        query = query.where(PracticeRecord.answered_at > reset_at)
    return query.distinct()


async def get_sequential_practice_questions(
    db: AsyncSession,
    *,
    user_id: int,
    subject_id: int,
    subject_ids: list[int],
    count: int = 20,
    knowledge_points: list[str] | None = None,
) -> tuple[list[Question], dict]:
    """Return the next unanswered questions in stable ``Question.id`` order."""
    if len(subject_ids) != 1 or subject_ids[0] != subject_id:
        raise ValueError("顺序练习仅支持单一具体科目")

    latest_revision_matches_subject = latest_question_revision_scope_condition(
        [subject_id],
        SEQUENTIAL_ANSWERABLE_QUESTION_TYPES,
    )
    conditions = [
        Question.is_active,
        Question.review_status == "approved",
        Question.subject_id == subject_id,
        latest_revision_matches_subject,
    ]
    if knowledge_points:
        conditions.extend(kp_exact_conditions(knowledge_points))

    reset_at = await _get_reset_at(db, user_id=user_id, subject_id=subject_id)
    answered_ids = _answered_ids_query(
        user_id=user_id, subject_id=subject_id, reset_at=reset_at,
    )

    total_questions = int((await db.scalar(
        select(func.count(Question.id)).where(and_(*conditions))
    )) or 0)
    completed_questions = int((await db.scalar(
        select(func.count(Question.id)).where(
            and_(*conditions), Question.id.in_(answered_ids),
        )
    )) or 0)

    result = await db.execute(
        select(Question)
        .where(and_(*conditions), Question.id.notin_(answered_ids))
        .options(selectinload(Question.subject_ref))
        .order_by(Question.id.asc())
        .limit(count)
    )
    questions = list(result.scalars().all())
    remaining = max(0, total_questions - completed_questions)
    progress = {
        "subject_id": subject_id,
        "total_questions": total_questions,
        "completed_questions": completed_questions,
        "remaining_questions": remaining,
        "cycle_completed": total_questions > 0 and remaining == 0,
        "next_question_id": questions[0].id if questions else None,
    }
    logger.info(
        "[Sequential Query] uid=%d subject_id=%d total=%d completed=%d remaining=%d returned=%d",
        user_id, subject_id, total_questions, completed_questions, remaining, len(questions),
    )
    return questions, progress


async def reset_sequential_progress(
    db: AsyncSession, *, user_id: int, subject_id: int,
) -> None:
    """Start a new round without deleting answer history or polluting stats."""
    now = utcnow()
    db.add(PracticeSession(
        user_id=user_id,
        subject_id=subject_id,
        request_id=f"seqreset:{user_id}:{subject_id}:{uuid4().hex}",
        mode=SEQUENTIAL_RESET_MODE,
        started_at=now,
        finished_at=now,
        duration_sec=0,
        question_count=0,
        answered_count=0,
        correct_count=0,
        wrong_count=0,
        status=SEQUENTIAL_RESET_STATUS,
    ))
    await db.commit()
    logger.info("[Sequential Reset] uid=%d subject_id=%d reset_at=%s", user_id, subject_id, now)
