"""Run the scored smart-practice branch while the caller owns its providers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from logging import Logger
from typing import Any

RecommendationResult = tuple[list[Any], dict[int, dict]]


@dataclass(slots=True)
class ScoredSupplementRequest:
    db: Any
    user_id: int
    subject_code: str
    count: int
    exclude_answered: bool
    no_repeat_days: int | None
    use_leitner: bool
    request_id: str | None
    scope_ids: list[int]
    skip_finalize: bool
    experiment_id: int | None
    variant_key: str | None
    logger: Logger
    load_scored: Callable[..., Awaitable[RecommendationResult]]
    load_fallback: Callable[..., Awaitable[RecommendationResult]]
    merge_results: Callable[..., RecommendationResult]
    finalize: Callable[..., Awaitable[RecommendationResult]]


async def run_scored_supplement(
    request: ScoredSupplementRequest,
) -> RecommendationResult | None:
    """Keep the scored result authoritative, then fill only its deficit."""
    try:
        scored, metadata = await request.load_scored(
            db=request.db,
            user_id=request.user_id,
            subject_code=request.subject_code,
            count=request.count,
            exclude_answered=request.exclude_answered,
            no_repeat_days=request.no_repeat_days,
            request_id=request.request_id,
            subject_ids=request.scope_ids,
        )
        if len(scored) >= request.count:
            return await _finalize(request, scored[: request.count], metadata)

        request.logger.info(
            "scored 策略题量不足 (%d/%d)，保留 scored 结果并 fallback 到 weakness_vector 补齐",
            len(scored),
            request.count,
        )
        fallback, fallback_metadata = await request.load_fallback(
            db=request.db,
            user_id=request.user_id,
            subject_code=request.subject_code,
            count=request.count - len(scored),
            exclude_answered=request.exclude_answered,
            no_repeat_days=request.no_repeat_days,
            use_leitner=request.use_leitner,
            exclude_ids={question.id for question in scored},
            subject_ids=request.scope_ids,
        )
        merged, merged_metadata = request.merge_results(
            scored,
            metadata,
            fallback,
            fallback_metadata,
            count=request.count,
        )
        return await _finalize(
            request, merged[: request.count], merged_metadata
        )
    except Exception:
        request.logger.warning(
            "scored 策略失败，fallback 到 weakness_vector", exc_info=True
        )
        return None


async def _finalize(
    request: ScoredSupplementRequest,
    questions: list[Any],
    metadata: dict[int, dict],
) -> RecommendationResult:
    return await request.finalize(
        questions,
        metadata,
        request.skip_finalize,
        request.db,
        request.user_id,
        request.subject_code,
        request_id=request.request_id,
        experiment_id=request.experiment_id,
        variant_key=request.variant_key,
    )
