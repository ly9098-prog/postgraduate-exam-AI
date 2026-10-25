"""Orchestrate smart-practice strategy selection while the service owns ports."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from logging import Logger
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

RecommendationResult = tuple[list[Any], dict[int, dict]]


@dataclass(slots=True)
class SmartPracticeRequest:
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
    subject_ids: list[int]
    logger: Logger
    resolve_experiment: Callable[..., Awaitable[dict]]
    resolve_scope_ids: Callable[[AsyncSession, str], Awaitable[list[int]]]
    run_scored: Callable[[dict, str, list[int]], Awaitable[RecommendationResult | None]]
    run_path: Callable[[dict, str, list[int]], Awaitable[RecommendationResult | None]]
    run_weakness: Callable[..., Awaitable[RecommendationResult]]


async def run_smart_practice(request: SmartPracticeRequest) -> RecommendationResult:
    """Resolve the active strategy, then delegate to its compatibility branch."""
    strategy, experiment_info = await _resolve_strategy(request)
    if strategy == "scored":
        result = await request.run_scored(experiment_info, strategy, request.subject_ids)
        if result is not None:
            return result
    if strategy == "path":
        result = await request.run_path(experiment_info, strategy, request.subject_ids)
        if result is not None:
            return result
    return await request.run_weakness(
        db=request.db,
        user_id=request.user_id,
        subject_code=request.subject_code,
        count=request.count,
        exclude_answered=request.exclude_answered,
        no_repeat_days=request.no_repeat_days,
        use_leitner=request.use_leitner,
        subject_ids=request.subject_ids,
        skip_finalize=request.skip_finalize,
        request_id=request.request_id,
        experiment_id=experiment_info.get("experiment_id"),
        variant_key=experiment_info.get("variant_key"),
    )


async def _resolve_strategy(
    request: SmartPracticeRequest,
) -> tuple[str, dict[str, int | str | None]]:
    strategy = request.smart_strategy
    experiment_info: dict[str, int | str | None] = {
        "experiment_id": None,
        "variant_key": None,
        "strategy_config_id": None,
    }
    try:
        resolved = await request.resolve_experiment(
            db=request.db,
            user_id=request.user_id,
            scene="practice_smart",
            default_strategy=strategy,
        )
        if resolved.get("source") == "experiment" and resolved.get("strategy"):
            strategy = resolved["strategy"]
            experiment_info["experiment_id"] = resolved.get("experiment_id")
            experiment_info["variant_key"] = resolved.get("variant_key")
    except Exception:
        request.logger.warning("实验策略解析失败，使用默认策略", exc_info=True)
    return normalize_smart_strategy(strategy), experiment_info


def normalize_smart_strategy(strategy: str | None) -> str:
    value = (strategy or "scored").strip().lower()
    return {
        "knowledge_path": "path",
        "hybrid_graph": "scored",
        "smart_scored": "scored",
        "weakness_vector": "weakness_vector",
    }.get(value, value)
