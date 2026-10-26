"""Immutable answer context and ordered revision-scoped projection effects."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession


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


@dataclass(frozen=True, slots=True)
class ProjectionAnswer:
    user_id: int
    question_id: int
    is_correct: bool
    used_time: int | None
    user_answer: str


def capture_projection_answer(record: _ProjectionSource) -> ProjectionAnswer:
    return ProjectionAnswer(
        record.user_id,
        record.question_id,
        record.is_correct,
        record.used_time,
        record.user_answer.strip(),
    )


async def _record_revision_behavior(
    db: AsyncSession,
    record: _ProjectionSource,
    revision: _RevisionSource,
    answer: ProjectionAnswer,
) -> None:
    from app.services.behavior_service import record_answer_behavior

    await record_answer_behavior(
        db=db,
        user_id=answer.user_id,
        question_id=answer.question_id,
        practice_record_id=record.id,
        question_version_id=record.question_version_id,
        time_spent_sec=answer.used_time or 0,
        is_first_correct=answer.is_correct,
        is_final_correct=answer.is_correct,
        user_answer=answer.user_answer,
        correct_answer=revision.answer,
        subject_id=revision.subject_id or record.subject_id,
        session_type=record.mode or "practice",
        commit=False,
    )


async def apply_revision_evidence(
    db: AsyncSession,
    record: _ProjectionSource,
    revision: _RevisionSource,
    answer: ProjectionAnswer,
    request_id: str | None,
) -> None:
    """Record immutable behavior, mastery and attribution in their original order."""
    await _record_revision_behavior(db, record, revision, answer)

    from app.services import mastery_service

    mastery_update = await mastery_service.update_user_knowledge_state_after_answer(
        db,
        answer.user_id,
        answer.question_id,
        answer.is_correct,
        used_time=answer.used_time,
        question_version_id=record.question_version_id,
    )

    from app.services import recommendation_log_service

    await recommendation_log_service.mark_recommendation_answered(
        db,
        answer.user_id,
        answer.question_id,
        answer.is_correct,
        request_id=request_id,
        mastery_after=(mastery_update or {}).get("mastery_after"),
        mastery_delta=(mastery_update or {}).get("mastery_delta"),
    )


async def apply_current_revision_state(
    db: AsyncSession,
    record: _ProjectionSource,
    answer: ProjectionAnswer,
) -> None:
    """Advance mutable review/adaptive state only after the entry's revision guard."""
    from app.services import question_review_service

    review_transition = (
        await question_review_service.update_user_question_state_after_answer(
            db,
            answer.user_id,
            answer.question_id,
            answer.is_correct,
            used_time=answer.used_time,
            answered_at=record.answered_at,
        )
    )

    from app.services import adaptive_learning_service

    await adaptive_learning_service.update_adaptive_state_after_answer(
        db,
        user_id=answer.user_id,
        question_id=answer.question_id,
        is_correct=answer.is_correct,
        answer_time_seconds=answer.used_time,
        answered_at=record.answered_at,
        is_due_review=review_transition.is_due_review,
        is_overdue_review=review_transition.is_overdue_review,
    )
