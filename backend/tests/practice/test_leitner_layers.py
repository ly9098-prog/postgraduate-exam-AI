"""Layer contracts for Leitner fallback scheduling."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pytest

from app.services.practice.leitner_layers import run_leitner_layers


class Question:
    def __init__(self, question_id: int) -> None:
        self.id = question_id


def conditions():
    now = datetime(2026, 10, 26, 8, 0, 0)
    return {
        "now": now,
        "due": lambda value: f"due:{value.isoformat()}",
        "soon": lambda value: f"soon:{value.isoformat()}",
        "oldest": lambda: "oldest-first",
    }


def _snapshot_call(due_value, kwargs):
    snapshot = {
        key: set(value) if isinstance(value, set) else value
        for key, value in kwargs.items()
    }
    return due_value, snapshot


@pytest.mark.asyncio
async def test_first_layer_short_circuits_without_later_queries(caplog):
    contract = conditions()
    calls = []

    async def load_questions(due_value, **kwargs):
        calls.append(_snapshot_call(due_value, kwargs))
        return [Question(i) for i in range(3)]

    async def unexpected_fallback(**kwargs):
        raise AssertionError("v1 fallback must not run")

    with caplog.at_level(logging.INFO, logger="app.services.practice_service"):
        result = await run_leitner_layers(
            now=contract["now"],
            logger=logging.getLogger("app.services.practice_service"),
            mode="random",
            count=3,
            load_questions=load_questions,
            due_condition=contract["due"],
            due_soon_condition=contract["soon"],
            oldest_first_order=contract["oldest"],
            load_v1_fallback=unexpected_fallback,
        )

    assert [question.id for question in result] == [0, 1, 2]
    assert len(calls) == 1
    assert "(layer: new+due)" in caplog.text


@pytest.mark.asyncio
async def test_layers_preserve_exclusions_and_shortfall_limits():
    contract = conditions()
    now = contract["now"]
    calls = []

    async def load_questions(due_value, **kwargs):
        calls.append(_snapshot_call(due_value, kwargs))
        if len(calls) == 1:
            return [Question(1)]
        if len(calls) == 2:
            return [Question(2)]
        return [Question(3)]

    async def load_v1_fallback(**kwargs):
        calls.append(("fallback", _snapshot_call(None, kwargs)[1]))
        return [Question(9)]

    result = await run_leitner_layers(
        now=now,
        logger=logging.getLogger("test"),
        mode="random",
        count=5,
        load_questions=load_questions,
        due_condition=contract["due"],
        due_soon_condition=contract["soon"],
        oldest_first_order=contract["oldest"],
        load_v1_fallback=load_v1_fallback,
    )

    assert [question.id for question in result] == [1, 2, 3, 9]
    assert calls[1] == (
        f"soon:{(now + timedelta(days=1)).isoformat()}",
        {"exclude_ids": {1}, "limit": 4},
    )
    assert calls[2][1]["exclude_ids"] == {1, 2}
    assert calls[2][1]["limit"] == 3
    assert calls[3] == ("fallback", {"existing_ids": {1, 2, 3}})


@pytest.mark.asyncio
async def test_oldest_layer_uses_thirty_one_day_window_and_order():
    contract = conditions()
    now = contract["now"]
    calls = []

    async def load_questions(due_value, **kwargs):
        calls.append(_snapshot_call(due_value, kwargs))
        if len(calls) == 1:
            return []
        return [Question(i) for i in range(2, 5)]

    async def unexpected_fallback(**kwargs):
        raise AssertionError("v1 fallback must not run")

    await run_leitner_layers(
        now=now,
        logger=logging.getLogger("test"),
        mode="sequential",
        count=4,
        load_questions=load_questions,
        due_condition=contract["due"],
        due_soon_condition=contract["soon"],
        oldest_first_order=contract["oldest"],
        load_v1_fallback=unexpected_fallback,
    )

    assert calls[2][0] == f"soon:{(now + timedelta(days=31)).isoformat()}"
    assert calls[2][1] == {
        "exclude_ids": {2, 3, 4},
        "limit": 1,
        "extra_order": "oldest-first",
    }
