"""Assemble basic and per-subject random eligibility before scheduling."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class BasicSelectionOptions:
    user_id: int
    knowledge_points: list[str] | None
    knowledge_point_ids: list[int] | None
    exclude_answered: bool
    no_repeat_days: int | None
    use_leitner: bool
    namespace: dict[str, Any]


async def run_basic_selection(
    db: Any,
    subject_code: str,
    *,
    count: int,
    mode: str,
    subject_ids: list[int] | None,
    options: BasicSelectionOptions,
) -> list:
    ports = options.namespace
    if subject_ids is not None:
        ids = subject_ids
    else:
        ids = await ports["resolve_subject_ids"](db, subject_code)
    subject_cond = ports["Question"].subject_id.in_(ids)
    conditions = [
        ports["Question"].is_active,
        subject_cond,
        ports["_practice_revision_scope_condition"](ids),
    ]
    _extend_knowledge_filters(conditions, options)
    if mode == ports["SEQUENTIAL_MODE"]:
        if len(ids) != 1:
            raise ValueError("顺序练习仅支持单一具体科目")
        questions, _progress = await ports["get_sequential_practice_questions"](
            db,
            user_id=options.user_id,
            subject_id=ids[0],
            subject_ids=ids,
            count=count,
            knowledge_points=options.knowledge_points,
        )
        return questions
    return await _load_scheduled_questions(db, conditions, mode, count, options)


def bind_random_bucket(
    options: BasicSelectionOptions,
) -> Callable[..., Awaitable[list]]:
    async def load_bucket(db: Any, sid: int, bucket_count: int) -> list:
        ports = options.namespace
        conditions = [
            ports["Question"].is_active,
            ports["Question"].subject_id == sid,
            ports["_practice_revision_scope_condition"]([sid]),
        ]
        _extend_knowledge_filters(conditions, options)
        return await _load_scheduled_questions(db, conditions, "random", bucket_count, options)

    return load_bucket


def _extend_knowledge_filters(conditions: list, options: BasicSelectionOptions) -> None:
    if options.knowledge_points:
        conditions.extend(options.namespace["kp_exact_conditions"](options.knowledge_points))
    if options.knowledge_point_ids:
        condition = options.namespace["kp_id_any_condition"](options.knowledge_point_ids)
        if condition is not None:
            conditions.append(condition)


async def _load_scheduled_questions(
    db: Any,
    conditions: list,
    mode: str,
    count: int,
    options: BasicSelectionOptions,
) -> list:
    if options.use_leitner:
        return await options.namespace["_get_questions_with_leitner"](
            db,
            options.user_id,
            conditions,
            mode,
            count,
            exclude_answered=options.exclude_answered,
            no_repeat_days=options.no_repeat_days,
        )
    return await options.namespace["_get_questions_v1_fallback"](
        db,
        conditions,
        mode,
        count,
        user_id=options.user_id,
        exclude_answered=options.exclude_answered,
        no_repeat_days=options.no_repeat_days,
    )
