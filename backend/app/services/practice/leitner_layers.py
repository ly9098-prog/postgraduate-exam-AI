"""Layered fallback orchestration for Leitner candidate loading."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from logging import Logger
from typing import Any

QuestionLoader = Callable[..., Awaitable[list]]


async def run_leitner_layers(
    *,
    now: datetime,
    logger: Logger,
    mode: str,
    count: int,
    load_questions: QuestionLoader,
    due_condition: Callable[[datetime], Any],
    due_soon_condition: Callable[[datetime], Any],
    oldest_first_order: Callable[[], Any],
    load_v1_fallback: Callable[..., Awaitable[list]],
) -> list:
    questions = await load_questions(due_condition(now))
    if _layer_complete(questions, count, logger, mode, "new+due"):
        return questions[:count]

    existing_ids = {question.id for question in questions}
    soon = now + timedelta(days=1)
    more = await load_questions(
        due_soon_condition(soon),
        exclude_ids=existing_ids,
        limit=count - len(questions),
    )
    questions.extend(more)
    existing_ids.update(question.id for question in more)
    if _layer_complete(questions, count, logger, mode, "due+1d"):
        return questions[:count]

    more = await load_questions(
        due_soon_condition(soon + timedelta(days=30)),
        exclude_ids=existing_ids,
        limit=count - len(questions),
        extra_order=oldest_first_order(),
    )
    questions.extend(more)
    existing_ids.update(question.id for question in more)
    if _layer_complete(questions, count, logger, mode, "oldest"):
        return questions[:count]

    v1_results = await load_v1_fallback(existing_ids=existing_ids)
    questions.extend(v1_results)
    logger.info(
        "[Leitner Query] mode=%s count=%d resultCount=%d (layer: v1-fallback)",
        mode,
        count,
        len(questions),
    )
    return questions[:count]


def _layer_complete(
    questions: list, count: int, logger: Logger, mode: str, layer: str
) -> bool:
    if len(questions) < count:
        return False
    logger.info(
        "[Leitner Query] mode=%s count=%d resultCount=%d (layer: %s)",
        mode,
        count,
        len(questions),
        layer,
    )
    return True
