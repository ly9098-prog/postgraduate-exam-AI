"""Coordinate one practice batch while the caller owns its transaction."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sequential_reservation import SequentialReservation
from app.schemas.practice import PracticeQuestionsResponse
from app.services.practice.batch_issuance import build_signed_practice_response
from app.services.practice.candidate_schedule import filter_due_candidates
from app.services.practice.candidate_selection import select_practice_candidates
from app.services.practice.final_candidates import prepare_final_candidates
from app.services.practice.request_assembly import (
    PracticeQuestionsRequest,
    prepare_practice_request,
)
from app.services.practice.request_observability import (
    log_practice_response,
    log_practice_scope,
)


@dataclass
class IssuedPracticeBatch:
    response: PracticeQuestionsResponse
    mode: str
    final_question_ids: set[int]
    reservation_request_id: str | None


async def issue_practice_questions(
    db: AsyncSession, request: PracticeQuestionsRequest,
) -> IssuedPracticeBatch:
    prepared = await prepare_practice_request(db, request)
    candidate_request = prepared.candidate
    candidates = await select_practice_candidates(db, candidate_request)
    questions = await filter_due_candidates(
        db, candidate_request, candidates.questions, mode=candidates.mode,
    )
    final = await prepare_final_candidates(
        db, candidate_request, questions,
        mode=candidates.mode, metadata=candidates.metadata,
        request_id=candidates.request_id,
    )
    final_ids = {int(question.id) for question in final.questions}
    log_practice_scope(
        prepared, include_children=request.include_children,
        mode=candidates.mode, questions=final.questions,
    )
    response = await build_signed_practice_response(
        db, candidate_request, candidates, final, prepared.issue_context,
    )
    log_practice_response(
        prepared.issue_context.trace_id, request.subject_id, final.questions,
    )
    return IssuedPracticeBatch(
        response, candidates.mode, final_ids, candidates.reservation_request_id,
    )


async def release_unissued_reservations(
    db: AsyncSession,
    *,
    user_id: int,
    subject_id: int,
    batch: IssuedPracticeBatch,
) -> None:
    """Drop only claims outside this final batch, within the caller's transaction."""
    await db.execute(
        delete(SequentialReservation).where(
            SequentialReservation.user_id == user_id,
            SequentialReservation.subject_id == subject_id,
            SequentialReservation.start_request_id == batch.reservation_request_id,
            SequentialReservation.question_id.notin_(batch.final_question_ids),
        )
    )
