"""Read-only canonical scope, trainability, graph and practice queries."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.subject_scope import (
    EXAM408_ALL_CODES,
    EXAM408_CORE_CODES,
    EXAM408_ROOT_CODE,
)
from app.core.time_utils import serialize_utc_datetime
from app.features.question_type import (
    QT_MULTI_BLANK_CHOICE,
    QT_MULTI_BLANK_MULTIPLE_CHOICE,
    QT_MULTIPLE_CHOICE,
    QT_SINGLE_CHOICE,
    QT_TRUE_FALSE,
)
from app.models.admin import QuestionVersion, QuestionVersionKnowledgePoint, Subject
from app.models.knowledge_edge import KnowledgeEdge
from app.models.knowledge_point import KnowledgePoint
from app.models.practice_record import PracticeRecord
from app.models.question import Question
from app.models.question_knowledge_point import QuestionKnowledgePoint
from app.models.syllabus import SyllabusKnowledgePoint
from app.models.user_knowledge_state import UserKnowledgeState

_ANSWERABLE_TYPES = (
    QT_SINGLE_CHOICE,
    QT_MULTIPLE_CHOICE,
    QT_TRUE_FALSE,
    QT_MULTI_BLANK_CHOICE,
    QT_MULTI_BLANK_MULTIPLE_CHOICE,
)


async def _load_core_subjects(db: AsyncSession) -> tuple[Subject | None, list[Subject]]:
    rows = list(
        (
            await db.scalars(select(Subject).where(Subject.code.in_(EXAM408_ALL_CODES)))
        ).all()
    )
    by_code = {str(row.code): row for row in rows if row.is_active}
    root = by_code.get(EXAM408_ROOT_CODE)
    cores = [by_code.get(code) for code in EXAM408_CORE_CODES]
    if root is None or any(subject is None for subject in cores):
        return None, []
    if any(int(subject.parent_id or 0) != int(root.id) for subject in cores):
        return None, []
    return root, [subject for subject in cores if subject is not None]


async def _load_trainable_counts(
    db: AsyncSession,
    subject_ids: list[int],
) -> dict[int, int]:
    if not subject_ids:
        return {}
    rows = await db.execute(
        select(
            QuestionKnowledgePoint.knowledge_point_id,
            func.count(func.distinct(Question.id)),
        )
        .join(Question, Question.id == QuestionKnowledgePoint.question_id)
        .join(QuestionVersion, QuestionVersion.id == Question.current_version_id)
        .join(
            KnowledgePoint,
            KnowledgePoint.id == QuestionKnowledgePoint.knowledge_point_id,
        )
        .where(
            KnowledgePoint.subject_id.in_(subject_ids),
            KnowledgePoint.is_active.is_(True),
            Question.subject_id == KnowledgePoint.subject_id,
            Question.is_active.is_(True),
            Question.review_status == "approved",
            QuestionVersion.question_id == Question.id,
            QuestionVersion.subject_id == Question.subject_id,
            QuestionVersion.question_type == Question.question_type,
            QuestionVersion.question_type.in_(_ANSWERABLE_TYPES),
            QuestionVersion.is_active.is_(True),
        )
        .group_by(QuestionKnowledgePoint.knowledge_point_id)
    )
    return {int(kp_id): int(count or 0) for kp_id, count in rows.all()}


async def _load_states(
    db: AsyncSession,
    user_id: int,
    subject_ids: list[int],
) -> dict[int, UserKnowledgeState]:
    if not subject_ids:
        return {}
    rows = await db.execute(
        select(UserKnowledgeState).where(
            UserKnowledgeState.user_id == user_id,
            UserKnowledgeState.subject_id.in_(subject_ids),
        )
    )
    return {int(state.knowledge_point_id): state for state in rows.scalars().all()}


async def _recent_answers(
    db: AsyncSession, user_id: int, knowledge_point_id: int
) -> list[dict]:
    rows = await db.execute(
        select(
            PracticeRecord.is_correct,
            PracticeRecord.used_time,
            PracticeRecord.answered_at,
        )
        .join(
            QuestionVersionKnowledgePoint,
            QuestionVersionKnowledgePoint.question_version_id
            == PracticeRecord.question_version_id,
        )
        .where(
            PracticeRecord.user_id == user_id,
            QuestionVersionKnowledgePoint.knowledge_point_id == knowledge_point_id,
        )
        .order_by(PracticeRecord.answered_at.desc(), PracticeRecord.id.desc())
        .limit(10)
    )
    return [
        {
            "is_correct": bool(row[0]),
            "used_time": int(row[1]) if row[1] is not None else None,
            "answered_at": serialize_utc_datetime(row[2]) if row[2] else None,
        }
        for row in rows.all()
    ]


async def _load_overview_points(
    db: AsyncSession,
    subject_ids: list[int],
    memberships: dict[int, SyllabusKnowledgePoint],
) -> list[KnowledgePoint]:
    active_kp_ids = list(memberships)
    return (
        list(
            (
                await db.scalars(
                    select(KnowledgePoint)
                    .where(
                        KnowledgePoint.subject_id.in_(subject_ids),
                        KnowledgePoint.id.in_(active_kp_ids)
                        if active_kp_ids
                        else False,
                    )
                    .order_by(KnowledgePoint.subject_id.asc(), KnowledgePoint.id.asc())
                )
            ).all()
        )
        if active_kp_ids
        else []
    )


async def _load_subject_points(
    db: AsyncSession,
    subject_id: int,
    memberships: dict[int, SyllabusKnowledgePoint],
    *,
    ordered: bool = False,
) -> list[KnowledgePoint]:
    active_kp_ids = list(memberships)
    if not active_kp_ids:
        return []
    statement = select(KnowledgePoint).where(
        KnowledgePoint.subject_id == subject_id,
        KnowledgePoint.id.in_(active_kp_ids) if active_kp_ids else False,
    )
    if ordered:
        statement = statement.order_by(KnowledgePoint.id.asc())
    return list((await db.scalars(statement)).all())


async def _load_parent_edges(db: AsyncSession, subject_id: int) -> list[KnowledgeEdge]:
    return list(
        (
            await db.scalars(
                select(KnowledgeEdge).where(
                    KnowledgeEdge.subject_id == subject_id,
                    KnowledgeEdge.is_active.is_(True),
                    KnowledgeEdge.relation_type == "parent",
                )
            )
        ).all()
    )


async def _load_point(
    db: AsyncSession, knowledge_point_id: int
) -> KnowledgePoint | None:
    return (
        await db.execute(
            select(KnowledgePoint).where(KnowledgePoint.id == knowledge_point_id)
        )
    ).scalar_one_or_none()


async def _load_relation_edges(
    db: AsyncSession, point: KnowledgePoint
) -> list[KnowledgeEdge]:
    return list(
        (
            await db.scalars(
                select(KnowledgeEdge).where(
                    KnowledgeEdge.subject_id == point.subject_id,
                    KnowledgeEdge.is_active.is_(True),
                    (
                        (KnowledgeEdge.source_knowledge_point_id == point.id)
                        | (KnowledgeEdge.target_knowledge_point_id == point.id)
                    ),
                )
            )
        ).all()
    )
