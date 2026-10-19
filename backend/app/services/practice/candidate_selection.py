"""Select practice candidates without owning HTTP or batch issuance."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.question import Question
from app.services import practice_service as svc
from app.services import recommendation_log_service

logger = logging.getLogger(__name__)


class PracticeCandidateError(ValueError):
    """A candidate request cannot be fulfilled under the existing contract."""


@dataclass
class PracticeCandidateRequest:
    user_id: int
    subject_id: int
    subject_code: str
    subject_ids: list[int]
    count: int
    mode: str
    knowledge_points: list[str] | None
    knowledge_point_ids: list[int] | None
    include_descendants: bool
    exclude_answered: bool
    no_repeat_days: int | None
    use_leitner: bool
    source_question_id: int | None
    targeted_question_ids: list[int]
    start_request_id: str | None
    smart_strategy: str

    def query_filters(self) -> dict[str, Any]:
        """Only the filters shared by the existing candidate providers."""
        return {
            "user_id": self.user_id,
            "subject_code": self.subject_code,
            "subject_ids": self.subject_ids,
            "exclude_answered": self.exclude_answered,
            "no_repeat_days": self.no_repeat_days,
            "use_leitner": self.use_leitner,
        }


@dataclass
class PracticeCandidates:
    questions: list[Question]
    mode: str
    metadata: dict[int, dict] = field(default_factory=dict)
    request_id: str | None = None
    sequential_progress: dict | None = None
    reservation_request_id: str | None = None


async def select_practice_candidates(
    db: AsyncSession,
    request: PracticeCandidateRequest,
) -> PracticeCandidates:
    """Dispatch providers while leaving final revision guards to issuance."""
    if request.targeted_question_ids:
        return await _select_targeted(db, request)
    if request.mode == "similar":
        return await _select_similar(db, request)
    if request.mode == "sequential":
        return await _select_sequential(db, request)
    if request.mode == "smart":
        return await _select_smart(db, request)
    return await _select_random(db, request)


async def _select_targeted(
    db: AsyncSession,
    request: PracticeCandidateRequest,
) -> PracticeCandidates:
    questions = await svc.get_targeted_practice_questions(
        db,
        question_ids=request.targeted_question_ids,
        subject_ids=request.subject_ids,
    )
    returned_ids = [int(question.id) for question in questions]
    if returned_ids != request.targeted_question_ids:
        missing_ids = [
            qid for qid in request.targeted_question_ids if qid not in set(returned_ids)
        ]
        raise PracticeCandidateError(f"定向题目已失效或超出当前科目范围: {missing_ids}")
    return PracticeCandidates(questions, request.mode)


async def _select_random(
    db: AsyncSession,
    request: PracticeCandidateRequest,
) -> PracticeCandidates:
    filters = request.query_filters()
    if request.include_descendants and request.knowledge_point_ids:
        questions = await svc.get_knowledge_scope_practice_questions(
            db=db,
            **filters,
            count=request.count,
            knowledge_point_ids=request.knowledge_point_ids,
        )
    else:
        filters.update(
            count=min(100, request.count + max(5, request.count // 2)),
            knowledge_points=(
                request.knowledge_points if not request.knowledge_point_ids else None
            ),
            knowledge_point_ids=request.knowledge_point_ids,
        )
        if len(request.subject_ids) > 1:
            questions = await svc.get_aggregated_random_questions(db=db, **filters)
        else:
            questions = await svc.get_practice_questions(
                db=db, mode=request.mode, **filters
            )
    return PracticeCandidates(questions, request.mode)


async def _select_similar(
    db: AsyncSession,
    request: PracticeCandidateRequest,
) -> PracticeCandidates:
    if not request.source_question_id:
        logger.warning("similar 模式缺少 source_question_id，回退到 random")
        # Preserve the legacy leaf-provider fallback even for aggregated scopes.
        questions = await svc.get_practice_questions(
            db=db,
            **request.query_filters(),
            count=min(100, request.count + max(5, request.count // 2)),
            mode="random",
            knowledge_points=request.knowledge_points,
        )
        return PracticeCandidates(questions, "random")
    request_id = str(uuid4())
    questions, metadata = await svc.get_similar_practice_questions(
        db=db,
        **request.query_filters(),
        source_question_id=request.source_question_id,
        count=request.count,
    )
    await _log_similar_recommendations(db, request, metadata, request_id)
    return PracticeCandidates(questions, request.mode, metadata, request_id)


async def _log_similar_recommendations(
    db: AsyncSession,
    request: PracticeCandidateRequest,
    metadata: dict[int, dict],
    request_id: str,
) -> None:
    try:
        recommendations = [
            {
                "question_id": qid,
                "subject": meta.get("subject", request.subject_code),
                "recommend_score": meta.get("recommend_score"),
                "similarity": meta.get("similarity"),
                "reason": meta.get("recommend_reason"),
            }
            for qid, meta in metadata.items()
        ]
        if recommendations:
            await recommendation_log_service.create_recommendation_logs_isolated(
                db=db,
                user_id=request.user_id,
                recommendations=recommendations,
                scene="similar",
                strategy="vector_plus_rule",
                request_id=request_id,
                source_question_id=request.source_question_id,
            )
    except Exception:
        logger.warning("similar 推荐日志写入失败", exc_info=True)


async def _select_sequential(
    db: AsyncSession,
    request: PracticeCandidateRequest,
) -> PracticeCandidates:
    try:
        reservation_id = str(
            request.start_request_id or f"seqstart:{request.user_id}:{uuid4().hex}"
        ).strip()
        questions, progress = await svc.get_sequential_practice_questions(
            db=db,
            user_id=request.user_id,
            subject_id=request.subject_id,
            subject_ids=request.subject_ids,
            count=request.count,
            knowledge_points=request.knowledge_points,
            reservation_request_id=reservation_id,
        )
    except ValueError as exc:
        raise PracticeCandidateError(str(exc)) from exc
    return PracticeCandidates(
        questions,
        request.mode,
        sequential_progress=progress,
        reservation_request_id=reservation_id,
    )


async def _select_smart(
    db: AsyncSession,
    request: PracticeCandidateRequest,
) -> PracticeCandidates:
    request_id = str(uuid4())
    provider = (
        svc.get_aggregated_smart_questions
        if len(request.subject_ids) > 1
        else svc.get_smart_practice_questions
    )
    questions, metadata = await provider(
        db=db,
        **request.query_filters(),
        count=request.count,
        request_id=request_id,
        smart_strategy=request.smart_strategy,
    )
    return PracticeCandidates(questions, request.mode, metadata, request_id)
