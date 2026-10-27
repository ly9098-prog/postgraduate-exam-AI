"""Characterize the service's scheduling adapters before extracting them."""

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services import practice_service as svc

NOW = datetime(2026, 10, 27, 8)


@pytest.fixture
def ports(monkeypatch):
    trace = []
    excluded = object()
    db = SimpleNamespace(scalar=object(), execute=object())
    logger = Mock()
    monkeypatch.setattr(svc, "logger", logger)
    monkeypatch.setattr(svc, "utcnow", lambda: trace.append("clock") or NOW)

    def exclusion(**kwargs):
        trace.append(("exclusion", kwargs))
        return excluded

    monkeypatch.setattr(svc, "_build_excluded_question_subquery", exclusion)
    monkeypatch.setattr(svc, "due_condition", lambda date: ("due", date))
    monkeypatch.setattr(svc, "due_soon_condition", lambda date: ("soon", date))
    monkeypatch.setattr(svc, "oldest_first_order", lambda: "oldest")
    return SimpleNamespace(
        trace=trace,
        excluded=excluded,
        db=db,
        logger=logger,
        conditions=[object()],
        requests=[],
        calls=[],
        fallback=[],
    )


def bind_loaders(monkeypatch, ports, batches):
    async def query(request, due, **kwargs):
        ports.requests.append(request)
        ports.calls.append(
            (
                due,
                {
                    key: set(value) if isinstance(value, set) else value
                    for key, value in kwargs.items()
                },
            )
        )
        return [SimpleNamespace(id=qid) for qid in batches[len(ports.calls) - 1]]

    async def fallback(*args, **kwargs):
        ports.fallback.append((args, kwargs))
        return [SimpleNamespace(id=99), SimpleNamespace(id=100)]

    monkeypatch.setattr(svc, "leitner_query", query)
    monkeypatch.setattr(svc, "_get_questions_v1_fallback", fallback)


@pytest.mark.asyncio
@pytest.mark.parametrize("stop", [0, 1, 2, 3])
@pytest.mark.parametrize("mode", ["random", "custom-order"])
@pytest.mark.parametrize("exclude,days", [(False, None), (True, None), (False, 30)])
async def test_layer_arguments_and_repeat_guard(
    monkeypatch, ports, stop, mode, exclude, days
):
    batches = [[], [], []]
    batches[: min(stop + 1, 3)] = [[i + 1] for i in range(min(stop + 1, 3))]
    count = stop + 1 if stop < 3 else 5
    bind_loaders(monkeypatch, ports, batches)
    sampler = svc._random_sample_query
    result = await svc._get_questions_with_leitner(
        ports.db,
        7,
        ports.conditions,
        mode,
        count,
        exclude_answered=exclude,
        no_repeat_days=days,
    )
    assert [q.id for q in result] == (
        list(range(1, stop + 2)) if stop < 3 else [1, 2, 3, 99, 100]
    )
    assert ports.trace == [
        "clock",
        (
            "exclusion",
            {
                "user_id": 7,
                "exclude_answered": exclude,
                "no_repeat_days": days,
            },
        ),
    ]
    assert len(ports.calls) == min(stop + 1, 3)
    request = ports.requests[0]
    assert all(value is request for value in ports.requests)
    assert request.base_conditions is ports.conditions
    assert request.excluded_sub is ports.excluded
    assert request.random_sample is sampler
    assert request.scalar is ports.db.scalar and request.execute is ports.db.execute
    assert (request.user_id, request.mode, request.count) == (7, mode, count)
    expected_calls = [
        (("due", NOW), {"exclude_ids": None, "limit": None, "extra_order": None}),
        (
            ("soon", NOW + timedelta(days=1)),
            {
                "exclude_ids": {1},
                "limit": count - 1,
                "extra_order": None,
            },
        ),
        (
            ("soon", NOW + timedelta(days=31)),
            {
                "exclude_ids": {1, 2},
                "limit": count - 2,
                "extra_order": "oldest",
            },
        ),
    ]
    assert ports.calls == expected_calls[: len(ports.calls)]
    if stop == 3:
        args, kwargs = ports.fallback[0]
        assert args == (ports.db, ports.conditions, mode, 2)
        assert args[1] is ports.conditions
        assert kwargs == {
            "user_id": 7,
            "exclude_answered": exclude,
            "no_repeat_days": days,
            "exclude_ids": {1, 2, 3},
        }
    else:
        assert ports.fallback == []
    assert ports.logger.info.call_count == 1
    assert ports.logger.info.call_args.args[1:3] == (mode, count)


@pytest.mark.asyncio
async def test_dynamic_query_and_fallback_ports_but_captured_request(
    monkeypatch, ports
):
    original_execute = ports.db.execute
    original_sampler = svc._random_sample_query

    async def replacement(request, due, **kwargs):
        assert request.execute is original_execute
        assert request.random_sample is original_sampler
        ports.trace.append("replacement")
        return []

    async def fallback(*args, **kwargs):
        ports.trace.append("new-fallback")
        assert kwargs["exclude_ids"] == {1}
        return [SimpleNamespace(id=9)]

    async def initial(request, due, **kwargs):
        ports.trace.append("initial")
        monkeypatch.setattr(svc, "leitner_query", replacement)
        monkeypatch.setattr(svc, "_get_questions_v1_fallback", fallback)
        monkeypatch.setattr(svc, "_random_sample_query", object())
        ports.db.execute = object()
        return [SimpleNamespace(id=1)]

    monkeypatch.setattr(svc, "leitner_query", initial)
    result = await svc._get_questions_with_leitner(
        ports.db,
        7,
        ports.conditions,
        "random",
        3,
    )
    assert [q.id for q in result] == [1, 9]
    assert ports.trace[2:] == ["initial", "replacement", "replacement", "new-fallback"]


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["clock", "exclusion", "query", "fallback", "log"])
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_failures_and_cancellation_propagate(
    monkeypatch, ports, stage, error_type
):
    error = error_type("synthetic failure")
    bind_loaders(monkeypatch, ports, [[], [], []])

    def fail(*args, **kwargs):
        raise error

    async def async_fail(*args, **kwargs):
        raise error

    targets = {
        "clock": ("utcnow", fail),
        "exclusion": ("_build_excluded_question_subquery", fail),
        "query": ("leitner_query", async_fail),
        "fallback": ("_get_questions_v1_fallback", async_fail),
    }
    if stage == "log":
        ports.logger.info.side_effect = error
    else:
        name, function = targets[stage]
        monkeypatch.setattr(svc, name, function)
    with pytest.raises(error_type) as caught:
        await svc._get_questions_with_leitner(
            ports.db, 7, ports.conditions, "random", 5
        )
    assert caught.value is error
    expected_queries = {"clock": 0, "exclusion": 0, "query": 0, "fallback": 3, "log": 3}
    assert len(ports.calls) == expected_queries[stage]
    assert len(ports.fallback) == (1 if stage == "log" else 0)


@pytest.mark.asyncio
async def test_actual_task_cancellation_does_not_invoke_fallback(monkeypatch, ports):
    entered = asyncio.Event()
    finalized = []

    async def query(*args, **kwargs):
        entered.set()
        try:
            await asyncio.Future()
        finally:
            finalized.append(True)

    bind_loaders(monkeypatch, ports, [[], [], []])
    monkeypatch.setattr(svc, "leitner_query", query)
    task = asyncio.create_task(
        svc._get_questions_with_leitner(ports.db, 7, ports.conditions, "random", 5)
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=2)
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert finalized == [True]
    assert ports.fallback == []
    ports.logger.info.assert_not_called()


@pytest.mark.asyncio
async def test_fallback_shortfall_uses_unique_ids_and_retains_candidate_order(
    monkeypatch, ports
):
    bind_loaders(monkeypatch, ports, [[1, 1], [2], [2]])
    result = await svc._get_questions_with_leitner(
        ports.db,
        7,
        ports.conditions,
        "random",
        5,
    )
    assert [q.id for q in result] == [1, 1, 2, 2, 99]
    assert ports.calls[1][1]["limit"] == 3
    assert ports.calls[2][1]["limit"] == 2
    assert ports.fallback[0][0][3] == 3
    assert ports.fallback[0][1]["exclude_ids"] == {1, 2}


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", [2, 3])
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_later_query_failure_stops_remaining_work(
    monkeypatch, ports, stage, error_type
):
    error = error_type("later query")
    calls = []
    bind_loaders(monkeypatch, ports, [[], [], []])

    async def query(*args, **kwargs):
        calls.append(len(calls) + 1)
        if len(calls) == stage:
            raise error
        return [SimpleNamespace(id=len(calls))]

    monkeypatch.setattr(svc, "leitner_query", query)
    with pytest.raises(error_type) as caught:
        await svc._get_questions_with_leitner(
            ports.db,
            7,
            ports.conditions,
            "random",
            5,
        )
    assert caught.value is error
    assert calls == list(range(1, stage + 1))
    assert ports.fallback == []
    ports.logger.info.assert_not_called()
