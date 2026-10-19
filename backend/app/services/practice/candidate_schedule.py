"""Apply the final user-question schedule guard to recommendation candidates."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.question import Question
from app.services import practice_service as svc
from app.services import question_review_service
from app.services.practice.candidate_selection import PracticeCandidateRequest

logger = logging.getLogger(__name__)


async def filter_due_candidates(
    db: AsyncSession,
    request: PracticeCandidateRequest,
    questions: list[Question],
    *,
    mode: str,
) -> list[Question]:
    """Preserve ranking, due-only fallback and the original merge semantics."""
    if not request.use_leitner or mode not in {"smart", "similar"} or not questions:
        return questions
    due_ids = await question_review_service.get_due_question_ids(
        db,
        request.user_id,
        [int(question.id) for question in questions],
    )
    filtered = [question for question in questions if int(question.id) in due_ids]
    if len(filtered) != len(questions):
        logger.info(
            "[PRACTICE_LEITNER_GUARD] uid=%s mode=%s filtered=%s remaining=%s",
            request.user_id,
            mode,
            len(questions) - len(filtered),
            len(filtered),
        )
    missing_count = max(0, request.count - len(filtered))
    if missing_count:
        fallback = await svc.get_practice_questions(
            db=db,
            **request.query_filters(),
            count=min(100, missing_count + len(filtered)),
            mode="random",
            knowledge_points=request.knowledge_points,
            knowledge_point_ids=request.knowledge_point_ids,
        )
        fallback_due_ids = await question_review_service.get_due_question_ids(
            db,
            request.user_id,
            [int(question.id) for question in fallback],
        )
        existing_ids = {int(question.id) for question in filtered}
        for question in fallback:
            if (
                int(question.id) in fallback_due_ids
                and int(question.id) not in existing_ids
            ):
                filtered.append(question)
                existing_ids.add(int(question.id))
            if len(filtered) >= request.count:
                break
    return filtered[: request.count]
