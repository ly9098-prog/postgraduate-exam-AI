"""Bind practice eligibility and loaders to the existing Leitner scheduler."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

QuestionLoader = Callable[..., Awaitable[list]]


@dataclass(slots=True)
class LeitnerSelectionRequest:
    db: Any
    user_id: int
    base_conditions: list
    mode: str
    count: int
    exclude_answered: bool
    no_repeat_days: int | None
    namespace: dict[str, Any]


async def run_leitner_selection(request: LeitnerSelectionRequest) -> list:
    ports = request.namespace
    now = ports["utcnow"]()
    excluded_sub = ports["_build_excluded_question_subquery"](
        user_id=request.user_id,
        exclude_answered=request.exclude_answered,
        no_repeat_days=request.no_repeat_days,
    )
    query_request = ports["LeitnerQueryRequest"](
        user_id=request.user_id,
        base_conditions=request.base_conditions,
        mode=request.mode,
        count=request.count,
        excluded_sub=excluded_sub,
        random_sample=ports["_random_sample_query"],
        scalar=request.db.scalar,
        execute=request.db.execute,
    )
    load_questions, load_v1_fallback = _bind_loaders(request, query_request)
    return await ports["run_leitner_layers"](
        now=now,
        logger=ports["logger"],
        mode=request.mode,
        count=request.count,
        load_questions=load_questions,
        due_condition=ports["due_condition"],
        due_soon_condition=ports["due_soon_condition"],
        oldest_first_order=ports["oldest_first_order"],
        load_v1_fallback=load_v1_fallback,
    )


def _bind_loaders(
    request: LeitnerSelectionRequest, query_request: Any
) -> tuple[QuestionLoader, QuestionLoader]:
    async def load_questions(
        due_condition: Any,
        exclude_ids: set[int] | None = None,
        limit: int | None = None,
        extra_order: Any = None,
    ) -> list:
        return await request.namespace["leitner_query"](
            query_request,
            due_condition,
            exclude_ids=exclude_ids,
            limit=limit,
            extra_order=extra_order,
        )

    async def load_v1_fallback(*, existing_ids: set[int]) -> list:
        return await request.namespace["_get_questions_v1_fallback"](
            request.db,
            request.base_conditions,
            request.mode,
            request.count - len(existing_ids),
            user_id=request.user_id,
            exclude_answered=request.exclude_answered,
            no_repeat_days=request.no_repeat_days,
            exclude_ids=existing_ids,
        )

    return load_questions, load_v1_fallback
