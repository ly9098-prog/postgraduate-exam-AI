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
    QT_MULTI_BLANK_MULTIPLE_CHOICE,
    QT_MULTIPLE_CHOICE,
    QT_SINGLE_CHOICE,
    QT_TRUE_FALSE,
)
from app.models.practice_record import PracticeRecord
from app.models.practice_session import PracticeSession
from app.models.question import Question
from app.models.sequential_reservation import SequentialReservation
from app.services.knowledge_point_service import kp_exact_conditions
from app.services.practice.sequential_selection import (
    ReservationScope,
    SelectionPorts,
    count_sequential_progress,
    expired_reservations,
    fill_reservations,
    load_reserved_questions,
    read_request_reservations,
    sequential_progress,
)
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
        QT_MULTI_BLANK_MULTIPLE_CHOICE,
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


def _selection_ports() -> SelectionPorts:
    """Resolve historical SQL/model ports when each query is built."""
    return SelectionPorts(
        select=select,
        delete=delete,
        exists=exists,
        and_=and_,
        literal=literal,
        func=func,
        selectinload=selectinload,
        question=Question,
        reservation=SequentialReservation,
    )


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
    """Claim with atomic INSERT/SELECT; retry conflicts from the next free IDs."""
    scope = ReservationScope(
        user_id=user_id,
        subject_id=subject_id,
        scope_key=scope_key,
        start_request_id=start_request_id,
        now=now,
        expires_at=now + timedelta(seconds=SEQUENTIAL_RESERVATION_TTL_SEC),
    )
    await db.execute(expired_reservations(scope, _selection_ports()))
    existing_ids = await read_request_reservations(db, scope, _selection_ports)
    if existing_ids:
        return existing_ids
    dialect = db.get_bind().dialect.name
    insert_factory = pg_insert if dialect == "postgresql" else sqlite_insert
    return await fill_reservations(
        db,
        scope,
        count=count,
        conditions=conditions,
        answered_ids=answered_ids,
        dialect=dialect,
        insert_factory=insert_factory,
        get_ports=_selection_ports,
    )


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

    conditions = _sequential_conditions(subject_id, knowledge_points)
    reset_at = await _get_reset_at(db, user_id=user_id, subject_id=subject_id)
    answered_ids = _answered_ids_query(
        user_id=user_id,
        subject_id=subject_id,
        reset_at=reset_at,
    )
    start_request_id = _sequential_start_request_id(reservation_request_id, user_id)
    scope_key = _sequential_scope_key(knowledge_points)
    now = utcnow()

    total_questions, completed_questions = await count_sequential_progress(
        db,
        conditions,
        answered_ids,
        _selection_ports,
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
    questions = await load_reserved_questions(
        db, reserved_ids, conditions, _selection_ports()
    )
    return _sequential_result(
        user_id, subject_id, total_questions, completed_questions, questions
    )


def _sequential_conditions(subject_id: int, knowledge_points: list[str] | None) -> list:
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
    return conditions


def _sequential_start_request_id(
    reservation_request_id: str | None, user_id: int
) -> str:
    request_id = str(
        reservation_request_id or f"seqstart:{user_id}:{uuid4().hex}"
    ).strip()
    if not request_id or len(request_id) > 128:
        raise ValueError("顺序练习 start_request_id 无效")
    return request_id


def _sequential_result(
    user_id: int,
    subject_id: int,
    total_questions: int,
    completed_questions: int,
    questions: list,
) -> tuple[list[Question], dict]:
    progress = sequential_progress(
        subject_id, total_questions, completed_questions, questions
    )
    logger.info(
        "[Sequential Query] uid=%d subject_id=%d total=%d completed=%d remaining=%d returned=%d",
        user_id,
        subject_id,
        total_questions,
        completed_questions,
        progress["remaining_questions"],
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
