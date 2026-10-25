"""Branch adapters that keep smart-practice providers service-owned."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from logging import Logger
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

RecommendationResult = tuple[list[Any], dict[int, dict]]


@dataclass(slots=True)
class SmartBranchRequest:
    db: AsyncSession
    user_id: int
    subject_code: str
    count: int
    exclude_answered: bool
    no_repeat_days: int | None
    use_leitner: bool
    request_id: str | None
    skip_finalize: bool
    load_path: Callable[..., Awaitable[RecommendationResult]]
    load_fallback: Callable[..., RecommendationResult]
    merge_results: Callable[..., RecommendationResult]
    finalize: Callable[..., Awaitable[RecommendationResult]]
    build_conditions: Callable[..., Any]


@dataclass(slots=True)
class SmartBranchProviders:
    load_scored: Callable[..., Awaitable[RecommendationResult]]
    load_fallback: Callable[..., RecommendationResult]
    merge_results: Callable[..., RecommendationResult]
    finalize_scored: Callable[..., Awaitable[RecommendationResult]]
    finalize_path: Callable[..., Awaitable[RecommendationResult]]
    build_path_conditions: Callable[..., Any]
    load_path: Callable[..., Awaitable[RecommendationResult]]


def create_smart_branches(request: SmartBranchRequest, providers: SmartBranchProviders):
    """Build the exact scored/path callbacks consumed by the orchestrator."""

    async def run_scored_branch(
        experiment_info: dict,
        _strategy: str,
        branch_scope_ids: list[int],
    ) -> RecommendationResult | None:
        from app.services.practice.smart_scored_supplement import (
            ScoredSupplementRequest,
            run_scored_supplement,
        )

        return await run_scored_supplement(
            ScoredSupplementRequest(
                db=request.db,
                user_id=request.user_id,
                subject_code=request.subject_code,
                count=request.count,
                exclude_answered=request.exclude_answered,
                no_repeat_days=request.no_repeat_days,
                use_leitner=request.use_leitner,
                request_id=request.request_id,
                scope_ids=branch_scope_ids,
                skip_finalize=request.skip_finalize,
                experiment_id=experiment_info.get("experiment_id"),
                variant_key=experiment_info.get("variant_key"),
                logger=_branch_logger(),
                load_scored=providers.load_scored,
                load_fallback=providers.load_fallback,
                merge_results=providers.merge_results,
                finalize=providers.finalize_scored,
            )
        )

    async def run_path_branch(
        experiment_info: dict,
        _strategy: str,
        branch_scope_ids: list[int],
    ) -> RecommendationResult | None:
        from app.services.practice.smart_path_supplement import (
            SmartPathRequest,
            run_smart_path,
        )

        return await run_smart_path(
            SmartPathRequest(
                db=request.db,
                user_id=request.user_id,
                subject_code=request.subject_code,
                count=request.count,
                exclude_answered=request.exclude_answered,
                no_repeat_days=request.no_repeat_days,
                use_leitner=request.use_leitner,
                scope_ids=branch_scope_ids,
                skip_finalize=request.skip_finalize,
                experiment_id=experiment_info.get("experiment_id"),
                variant_key=experiment_info.get("variant_key"),
                request_id=request.request_id,
                logger=_branch_logger(),
                load_path=providers.load_path,
                load_fallback=providers.load_fallback,
                merge_results=providers.merge_results,
                finalize=providers.finalize_path,
                build_conditions=providers.build_path_conditions,
            )
        )

    async def run_weakness_branch(**kwargs) -> RecommendationResult:
        return await providers.load_fallback(**kwargs)

    return run_scored_branch, run_path_branch, run_weakness_branch


def _branch_logger() -> Logger:
    import logging

    return logging.getLogger("app.services.practice_service")
