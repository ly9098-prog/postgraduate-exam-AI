"""Validate the final candidate set before signing an immutable practice batch."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.question import Question
from app.services import practice_service as svc
from app.services import recommendation_log_service
from app.services.practice.candidate_selection import PracticeCandidateRequest

logger = logging.getLogger(__name__)


class PracticeCandidateConflictError(ValueError):
    """A targeted set changed between selection and issuance."""


@dataclass
class FinalPracticeCandidates:
    questions: list[Question]
    revision_ids: dict[int, int]
    metadata: dict[int, dict]


async def prepare_final_candidates(
    db: AsyncSession,
    request: PracticeCandidateRequest,
    questions: list[Question],
    *,
    mode: str,
    metadata: dict[int, dict],
    request_id: str | None,
) -> FinalPracticeCandidates:
    revision_ids = await svc.load_latest_question_revision_ids(
        db, [int(question.id) for question in questions]
    )
    questions = await svc.filter_questions_to_revision_scope(
        db, questions, request.subject_ids, revision_ids=revision_ids
    )
    questions = _deduplicate_in_scope(request, questions, mode)
    if request.targeted_question_ids:
        final_ids = [int(question.id) for question in questions]
        if final_ids != request.targeted_question_ids:
            missing_ids = [
                qid
                for qid in request.targeted_question_ids
                if qid not in set(final_ids)
            ]
            raise PracticeCandidateConflictError(
                f"定向题目在签发前已失效或超出当前科目范围: {missing_ids}"
            )
    final_ids = {int(question.id) for question in questions}
    metadata = {key: value for key, value in metadata.items() if int(key) in final_ids}
    await _retain_exposures(db, request.user_id, mode, request_id, final_ids)
    return FinalPracticeCandidates(questions, revision_ids, metadata)


def _deduplicate_in_scope(
    request: PracticeCandidateRequest,
    questions: list[Question],
    mode: str,
) -> list[Question]:
    scope = set(request.subject_ids)
    result = []
    seen: set[int] = set()
    duplicates: list[int] = []
    for question in questions:
        question_id = int(question.id)
        if question_id in seen:
            duplicates.append(question_id)
            continue
        seen.add(question_id)
        if question.subject_id in scope:
            result.append(question)
    if duplicates:
        logger.warning(
            "[PRACTICE_DUPLICATE_CANDIDATE] subject_id=%s mode=%s duplicate_ids=%s",
            request.subject_id,
            mode,
            sorted(set(duplicates)),
        )
    return result[: request.count]


async def _retain_exposures(
    db: AsyncSession,
    user_id: int,
    mode: str,
    request_id: str | None,
    question_ids: set[int],
) -> None:
    if request_id and mode in {"smart", "similar"}:
        try:
            await recommendation_log_service.retain_recommendation_logs_for_questions(
                db, user_id=user_id, request_id=request_id, question_ids=question_ids
            )
        except Exception:
            logger.warning(
                "推荐日志最终题目集合对齐失败 request_id=%s", request_id, exc_info=True
            )
