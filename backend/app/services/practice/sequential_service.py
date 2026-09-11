"""Strict sequential-practice progress.

This module is intentionally isolated from recommendation/Leitner code.  A
sequential session means deterministic coverage of one leaf subject; learning
state may be updated after answers, but it never changes which question is next.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import and_, delete, exists, func, literal, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
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
from app.models.sequential_reservation import SequentialReservation
from app.services.knowledge_point_service import kp_exact_conditions
from app.services.question_revision_service import (
    latest_question_revision_scope_condition,
)

logger = logging.getLogger(__name__)

SEQUENTIAL_MODE = "sequential"
SEQUENTIAL_RESET_MODE = "sequential_reset"
SEQUENTIAL_RESET_STATUS = "marker"
SEQUENTIAL_RESERVATION_TTL_SEC = 24 * 60 * 60

# Keep sequential mode aligned with the controls provided by quiz-runner.
# Free-text/subjective revisions remain in the bank but are not issuable here.
SEQUENTIAL_ANSWERABLE_QUESTION_TYPES = frozenset(
    {
        QT_SINGLE_CHOICE,
        QT_MULTIPLE_CHOICE,
        QT_TRUE_FALSE,
        QT_MULTI_BLANK_CHOICE,
    }
)


async def _get_reset_at(
    db: AsyncSession,
    *,
    user_id: int,
    subject_id: int,
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


def _sequential_scope_key(knowledge_points: list[str] | None) -> str:
    values = sorted(
        {str(value).strip() for value in (knowledge_points or []) if str(value).strip()}
    )
    payload = json.dumps(values, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def _reserve_sequential_questions(
    db: AsyncSession,
    *,
    user_id: int,
    subject_id: int,
    conditions: list,
    answered_ids,
    count: int,
    scope_key: str,
    start_request_id: str,
    now: datetime,
) -> list[int]:
    """Atomically claim the next questions with database-owned reservations.

    Each INSERT is an atomic candidate selection plus reservation write. The
    loop matters when another transaction wins one of the candidate rows while
    this statement is waiting on the unique constraint: a later statement then
    fills from the next unclaimed IDs without ever returning a duplicate.
    """
    expires_at = now + timedelta(seconds=SEQUENTIAL_RESERVATION_TTL_SEC)
    await db.execute(
        delete(SequentialReservation).where(
            SequentialReservation.user_id == user_id,
            SequentialReservation.subject_id == subject_id,
            SequentialReservation.scope_key == scope_key,
            SequentialReservation.expires_at <= now,
        )
    )

    existing_rows = await db.execute(
        select(SequentialReservation.question_id)
        .where(
            SequentialReservation.user_id == user_id,
            SequentialReservation.subject_id == subject_id,
            SequentialReservation.scope_key == scope_key,
            SequentialReservation.start_request_id == start_request_id,
            SequentialReservation.expires_at > now,
        )
        .order_by(SequentialReservation.question_id.asc())
    )
    existing_ids = [int(question_id) for question_id in existing_rows.scalars().all()]
    if existing_ids:
        return existing_ids

    selected_ids: list[int] = []
    dialect = db.get_bind().dialect.name
    insert_factory = pg_insert if dialect == "postgresql" else sqlite_insert
    while len(selected_ids) < count:
        remaining = count - len(selected_ids)
        active_reservation = exists(
            select(1).where(
                SequentialReservation.user_id == user_id,
                SequentialReservation.subject_id == subject_id,
                SequentialReservation.scope_key == scope_key,
                SequentialReservation.question_id == Question.id,
                SequentialReservation.expires_at > now,
            )
        )
        # Build the INSERT source explicitly so every selected question is
        # inserted in one atomic statement.
        source_conditions = [
            and_(*conditions),
            Question.id.notin_(answered_ids),
            ~active_reservation,
        ]
        source = select(
            literal(user_id).label("user_id"),
            literal(subject_id).label("subject_id"),
            Question.id.label("question_id"),
            literal(scope_key).label("scope_key"),
            literal(start_request_id).label("start_request_id"),
            literal(now).label("created_at"),
            literal(expires_at).label("expires_at"),
        ).where(*source_conditions)
        source = source.order_by(Question.id.asc()).limit(remaining)
        stmt = insert_factory(SequentialReservation).from_select(
            [
                "user_id",
                "subject_id",
                "question_id",
                "scope_key",
                "start_request_id",
                "created_at",
                "expires_at",
            ],
            source,
        )
        if dialect == "postgresql":
            stmt = stmt.on_conflict_do_nothing(
                constraint="uq_sequential_reservation_question"
            ).returning(SequentialReservation.question_id)
        else:
            stmt = stmt.on_conflict_do_nothing(
                index_elements=[
                    SequentialReservation.user_id,
                    SequentialReservation.subject_id,
                    SequentialReservation.scope_key,
                    SequentialReservation.question_id,
                ]
            ).returning(SequentialReservation.question_id)
        result = await db.execute(stmt)
        inserted = [int(question_id) for question_id in result.scalars().all()]
        inserted.sort()
        if not inserted:
            same_request_rows = await db.execute(
                select(SequentialReservation.question_id)
                .where(
                    SequentialReservation.user_id == user_id,
                    SequentialReservation.subject_id == subject_id,
                    SequentialReservation.scope_key == scope_key,
                    SequentialReservation.start_request_id == start_request_id,
                    SequentialReservation.expires_at > now,
                )
                .order_by(SequentialReservation.question_id.asc())
            )
            same_request_ids = [
                int(question_id) for question_id in same_request_rows.scalars().all()
            ]
            if same_request_ids:
                return same_request_ids
            # A concurrent transaction may have won every row in this
            # statement.  Re-evaluate the candidate pool under READ COMMITTED
            # before giving up, so later questions can fill the requested batch
            # after the conflicting reservation commits.
            candidate_exists = await db.scalar(
                select(Question.id).where(*source_conditions).limit(1)
            )
            if candidate_exists is not None:
                continue
            break
        selected_ids.extend(inserted)
    return selected_ids


async def get_sequential_practice_questions(
    db: AsyncSession,
    *,
    user_id: int,
    subject_id: int,
    subject_ids: list[int],
    count: int = 20,
    knowledge_points: list[str] | None = None,
    reservation_request_id: str | None = None,
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
        user_id=user_id,
        subject_id=subject_id,
        reset_at=reset_at,
    )
    start_request_id = str(
        reservation_request_id or f"seqstart:{user_id}:{uuid4().hex}"
    ).strip()
    if not start_request_id or len(start_request_id) > 128:
        raise ValueError("顺序练习 start_request_id 无效")
    scope_key = _sequential_scope_key(knowledge_points)
    now = utcnow()

    total_questions = int(
        (await db.scalar(select(func.count(Question.id)).where(and_(*conditions)))) or 0
    )
    completed_questions = int(
        (
            await db.scalar(
                select(func.count(Question.id)).where(
                    and_(*conditions),
                    Question.id.in_(answered_ids),
                )
            )
        )
        or 0
    )

    reserved_ids = await _reserve_sequential_questions(
        db,
        user_id=user_id,
        subject_id=subject_id,
        conditions=conditions,
        answered_ids=answered_ids,
        count=count,
        scope_key=scope_key,
        start_request_id=start_request_id,
        now=now,
    )
    if reserved_ids:
        result = await db.execute(
            select(Question)
            .where(Question.id.in_(reserved_ids), and_(*conditions))
            .options(selectinload(Question.subject_ref))
            .order_by(Question.id.asc())
        )
        by_id = {int(question.id): question for question in result.scalars().all()}
        questions = [by_id[qid] for qid in reserved_ids if qid in by_id]
    else:
        questions = []
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
        user_id,
        subject_id,
        total_questions,
        completed_questions,
        remaining,
        len(questions),
    )
    return questions, progress


async def reset_sequential_progress(
    db: AsyncSession,
    *,
    user_id: int,
    subject_id: int,
) -> None:
    """Start a new round without deleting answer history or polluting stats."""
    now = utcnow()
    db.add(
        PracticeSession(
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
        )
    )
    await db.commit()
    logger.info(
        "[Sequential Reset] uid=%d subject_id=%d reset_at=%s", user_id, subject_id, now
    )
