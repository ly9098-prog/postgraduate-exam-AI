"""Run scored fallback queries and merges while the caller keeps their policy."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.elements import ColumnElement

    from app.models.question import Question


@dataclass(slots=True)
class ScoredFallbackRequest:
    db: AsyncSession
    selected: list[Question]
    selected_ids: set[int]
    metadata: dict[int, dict]
    count: int
    fallback_level: int
    subject_condition: ColumnElement[bool]
    candidate_ids: set[int]
    excluded_subquery: ColumnElement[bool] | None
    scope_ids: list[int]
    revision_condition: Callable[[list[int]], ColumnElement[bool]]
    random_fill: Callable[..., Coroutine[Any, Any, Any]]
    repeat_fill: Callable[..., Coroutine[Any, Any, Any]]
    sample_query: Callable[..., Any]
    merge_fill: Callable[..., list[Question]]
    metadata_factory: Callable[[str, str], dict]
    base_conditions: list[ColumnElement[bool]] = field(default_factory=list)


@dataclass(slots=True)
class ScoredFallbackResult:
    questions: list[Question]
    fallback_level: int


async def run_scored_fallback(request: ScoredFallbackRequest) -> ScoredFallbackResult:
    """Keep level checks in order while delegating queries and result merging."""
    level = request.fallback_level
    if len(request.selected) < request.count:
        level = await _run_random_fallback(request, level)
    if len(request.selected) < request.count:
        level = await _run_repeat_fallback(request, level)
    return ScoredFallbackResult(request.selected, level)


async def _run_random_fallback(
    request: ScoredFallbackRequest,
    fallback_level: int,
) -> int:
    remaining = request.count - len(request.selected)
    from app.models.question import Question

    conditions = [
        *request.base_conditions,
        request.subject_condition,
        request.revision_condition(request.scope_ids),
        Question.id.notin_(request.candidate_ids | request.selected_ids),
    ]
    if request.excluded_subquery is not None:
        conditions.append(Question.id.notin_(request.excluded_subquery))
    fill_questions = await request.random_fill(request.db, conditions, remaining)
    request.merge_fill(
        request.selected, request.selected_ids, fill_questions, request.metadata,
        "随机补齐", "random_fallback", request.metadata_factory,
        skip_duplicates=False,
    )
    return max(fallback_level, 3)


async def _run_repeat_fallback(
    request: ScoredFallbackRequest,
    fallback_level: int,
) -> int:
    remaining = request.count - len(request.selected)
    from app.models.question import Question

    conditions = [
        *request.base_conditions,
        request.subject_condition,
        request.revision_condition(request.scope_ids),
        Question.id.notin_(request.selected_ids),
    ]
    repeat_questions = await request.repeat_fill(
        request.db, conditions, remaining, request.sample_query,
    )
    request.merge_fill(
        request.selected, request.selected_ids, repeat_questions, request.metadata,
        "题量不足，放宽重复限制补齐", "repeat_window_fallback",
        request.metadata_factory, skip_duplicates=True,
    )
    return max(fallback_level, 4)
