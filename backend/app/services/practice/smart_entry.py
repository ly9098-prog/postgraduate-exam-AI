"""Service-owned request assembly for the smart-practice entrypoint."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from logging import Logger
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.practice.smart_branches import (
    create_smart_branches,
    SmartBranchProviders,
    SmartBranchRequest,
)
from app.services.practice.smart_orchestrator import (
    SmartPracticeRequest,
    run_smart_practice,
)

RecommendationResult = tuple[list[Any], dict[int, dict]]


@dataclass(slots=True)
class SmartEntryRequest:
    db: AsyncSession
    user_id: int
    subject_code: str
    count: int
    exclude_answered: bool
    no_repeat_days: int | None
    use_leitner: bool
    request_id: str | None
    smart_strategy: str
    skip_finalize: bool
    subject_ids: list[int] | None
    logger: Logger
    resolve_subject_ids: Callable[[AsyncSession, str], Awaitable[list[int]]]
    resolve_experiment: Callable[..., Awaitable[dict]]
    load_scored: Callable[..., Awaitable[RecommendationResult]]
    load_fallback: Callable[..., RecommendationResult]
    merge_results: Callable[..., RecommendationResult]
    finalize: Callable[..., Awaitable[RecommendationResult]]
    build_conditions: Callable[..., Any]
    load_path: Callable[..., Awaitable[RecommendationResult]]
    run_weakness: Callable[..., Awaitable[RecommendationResult]]


async def run_smart_entry(request: SmartEntryRequest) -> RecommendationResult:
    # use_leitner is applied by issuance; this entry owns candidate strategy only.
    scope_ids = (
        request.subject_ids
        if request.subject_ids is not None
        else await request.resolve_subject_ids(request.db, request.subject_code)
    )
    run_scored, run_path, run_weakness = create_smart_branches(
        SmartBranchRequest(
            db=request.db,
            user_id=request.user_id,
            subject_code=request.subject_code,
            count=request.count,
            exclude_answered=request.exclude_answered,
            no_repeat_days=request.no_repeat_days,
            use_leitner=request.use_leitner,
            request_id=request.request_id,
            skip_finalize=request.skip_finalize,
            load_path=request.load_path,
            load_fallback=request.load_fallback,
            merge_results=request.merge_results,
            finalize=request.finalize,
            build_conditions=request.build_conditions,
        ),
        SmartBranchProviders(
            load_scored=request.load_scored,
            load_fallback=request.load_fallback,
            merge_results=request.merge_results,
            finalize_scored=request.finalize,
            finalize_path=request.finalize,
            build_path_conditions=request.build_conditions,
            load_path=request.load_path,
            run_weakness=request.run_weakness,
        ),
    )
    return await run_smart_practice(
        SmartPracticeRequest(
            db=request.db,
            user_id=request.user_id,
            subject_code=request.subject_code,
            count=request.count,
            exclude_answered=request.exclude_answered,
            no_repeat_days=request.no_repeat_days,
            use_leitner=request.use_leitner,
            request_id=request.request_id,
            smart_strategy=request.smart_strategy,
            skip_finalize=request.skip_finalize,
            subject_ids=scope_ids,
            logger=request.logger,
            resolve_experiment=request.resolve_experiment,
            resolve_scope_ids=request.resolve_subject_ids,
            run_scored=run_scored,
            run_path=run_path,
            run_weakness=run_weakness,
        )
    )
