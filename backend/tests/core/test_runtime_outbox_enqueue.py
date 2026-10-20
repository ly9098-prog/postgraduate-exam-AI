"""Outbox adapters preserve queue ownership, payload identity and results."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tests.core.runtime_outbox_enqueue_probe import outbox_enqueue_factory


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["http", "standalone"])
@pytest.mark.parametrize("schema_version", [-1, 0, 1, 2, 999])
@pytest.mark.parametrize("outcome", ["accepted", "rejected", "none", "error", "cancel"])
async def test_outbox_callback_preserves_argument_mapping_result_and_queue_errors(entry, schema_version, outcome):
    result = None if outcome == "none" else SimpleNamespace(accepted=outcome == "accepted", task_id="synthetic-id")
    error = asyncio.CancelledError() if outcome == "cancel" else RuntimeError("synthetic queue error")
    enqueue = AsyncMock(return_value=result)
    if outcome in {"error", "cancel"}:
        enqueue.side_effect = error
    callback = outbox_enqueue_factory(entry)(SimpleNamespace(enqueue_v2=enqueue))
    payload = {"nested": {"value": 1}, "items": [2, 3]}
    if outcome in {"error", "cancel"}:
        with pytest.raises(type(error)) as caught:
            await callback("synthetic-id", "synthetic-kind", payload, schema_version)
        assert caught.value is error
    else:
        assert await callback("synthetic-id", "synthetic-kind", payload, schema_version) is result
    enqueue.assert_awaited_once_with(
        "synthetic-kind", payload, task_id="synthetic-id", schema_version=schema_version,
    )
    assert enqueue.await_args.args[1] is payload
    assert payload == {"nested": {"value": 1}, "items": [2, 3]}


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["http", "standalone"])
async def test_callback_captures_queue_identity_but_resolves_current_method_on_each_await(entry):
    original = AsyncMock(return_value="first")
    replacement = AsyncMock(return_value="second")
    first_queue = SimpleNamespace(enqueue_v2=original)
    second_queue = SimpleNamespace(enqueue_v2=AsyncMock(return_value="unrelated"))
    build = outbox_enqueue_factory(entry)
    first, second = build(first_queue), build(second_queue)
    assert first is not second
    assert await first("id-1", "kind", {}, 1) == "first"
    first_queue.enqueue_v2 = replacement
    assert await first("id-2", "kind", {}, 2) == "second"
    second_queue.enqueue_v2.assert_not_awaited()
    assert await second("id-3", "kind", {}, 3) == "unrelated"
    original.assert_awaited_once()
    replacement.assert_awaited_once_with("kind", {}, task_id="id-2", schema_version=2)
