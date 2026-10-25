"""Execute one wrong-question prewarm using caller-owned session and providers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from logging import Logger
from typing import Any

from sqlalchemy import select

from app.models.wrong_question import WrongQuestion
from app.services.ai.prewarm_transition import (
    finish_prewarm_result,
    recovery_regenerated,
    revision_changed,
    skipped_not_found,
    superseded_regenerated,
    superseded_revision,
)


@dataclass(slots=True)
class PrewarmExecutionRequest:
    wrong_question_id: int
    user_id: int
    expected_revision: str | None
    force_regenerate: bool
    baseline_generated_at: str | None
    logger: Logger
    async_session: Callable[[], Any]
    build_revision: Callable[..., str]
    generated_at: Callable[[Any], str | None]
    analyze_error: Callable[..., Awaitable[dict]]
    failure_factory: Callable[[dict], Exception]


async def execute_prewarm(request: PrewarmExecutionRequest) -> dict:
    async with request.async_session() as db:
        wrong_question = await _load_wrong_question(request, db)
        if wrong_question is None:
            return skipped_not_found()

        if _revision_superseded(request, wrong_question):
            return superseded_revision()
        if _recovery_superseded(request, wrong_question):
            return superseded_regenerated()

        result = await request.analyze_error(
            db,
            request.user_id,
            request.wrong_question_id,
            force_regenerate=request.force_regenerate,
        )
        return finish_prewarm_result(
            result,
            wrong_question_id=request.wrong_question_id,
            user_id=request.user_id,
            expected_revision=request.expected_revision,
            logger=request.logger,
            failure_factory=request.failure_factory,
        )


async def _load_wrong_question(request: PrewarmExecutionRequest, db):
    result = await db.execute(
        select(WrongQuestion).where(
            WrongQuestion.id == request.wrong_question_id,
            WrongQuestion.user_id == request.user_id,
        )
    )
    wrong_question = result.scalar_one_or_none()
    if wrong_question is None:
        request.logger.info(
            "[prewarm] skipped_not_found id=%d uid=%d",
            request.wrong_question_id,
            request.user_id,
        )
    return wrong_question


def _revision_superseded(request: PrewarmExecutionRequest, wrong_question) -> bool:
    if not request.expected_revision:
        return False
    current_revision = request.build_revision(
        review_count=wrong_question.review_count,
        wrong_answer=wrong_question.wrong_answer,
    )
    changed = revision_changed(
        wrong_question=wrong_question,
        expected_revision=request.expected_revision,
        build_revision=request.build_revision,
    )
    if changed:
        request.logger.info(
            "[prewarm] superseded id=%d uid=%d expected_revision=%s current_revision=%s",
            request.wrong_question_id,
            request.user_id,
            request.expected_revision,
            current_revision,
        )
    return changed


def _recovery_superseded(request: PrewarmExecutionRequest, wrong_question) -> bool:
    if not request.force_regenerate or request.baseline_generated_at is None:
        return False
    if not recovery_regenerated(
        wrong_question=wrong_question,
        baseline_generated_at=request.baseline_generated_at,
        generated_at=request.generated_at,
    ):
        return False
    current_generated_at = request.generated_at(wrong_question.ai_analysis) or ""
    request.logger.info(
        "[prewarm] recovery_superseded id=%d uid=%d baseline=%s current=%s",
        request.wrong_question_id,
        request.user_id,
        request.baseline_generated_at or "empty",
        current_generated_at or "empty",
    )
    return True
