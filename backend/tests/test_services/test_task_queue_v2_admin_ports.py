"""Keep administrative callback lookup and normalization timing observable."""

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services import task_queue_service as svc
from tests.queue_admin_support import AdminHarness


@pytest.fixture(params=["corrupt", "cancel", "reaper"])
def harness(monkeypatch, request):
    return AdminHarness(monkeypatch, request.param)


@pytest.mark.asyncio
async def test_live_queue_methods_and_wire_config(monkeypatch, harness):
    state = harness
    acquire, load, evaluate, close = (
        state.queue._get_script_client,
        state.queue._load_scripts,
        state.queue._evalsha_or_reload,
        state.client.aclose,
    )
    seen = []

    async def new_close():
        seen.append("close")
        await close()

    async def new_eval(*args):
        seen.append("eval")
        monkeypatch.setattr(state.client, "aclose", new_close)
        return await evaluate(*args)

    async def new_load(client):
        seen.append("load")
        monkeypatch.setattr(state.queue, "_evalsha_or_reload", new_eval)
        monkeypatch.setattr(svc, "_V2_FENCING_PREFIX", "replacement-fencing")
        monkeypatch.setattr(
            svc, "settings", SimpleNamespace(TASK_QUEUE_CORRUPT_MAX=999)
        )
        monkeypatch.setattr(svc, "_FENCING_TOMBSTONE_TTL", 777)
        monkeypatch.setattr(svc, "_DEAD_HASH_TTL", 778)
        monkeypatch.setattr(svc, "_get_max_ready", lambda task_type: 888)
        monkeypatch.setattr(
            svc, "_v2_p_key", lambda task_type: f"replacement:{task_type}"
        )
        await load(client)

    async def new_acquire():
        client = await acquire()
        monkeypatch.setattr(state.queue, "_load_scripts", new_load)
        return client

    monkeypatch.setattr(state.queue, "_get_script_client", new_acquire)
    assert await state.run() == 1
    assert seen == ["load", "eval", "close"]
    assert "replacement:demo" in state.wire and "replacement-fencing" in state.wire
    if state.operation == "reaper":
        assert state.wire[-3:] == ("888", "999", "778")
    elif state.operation == "corrupt":
        assert state.wire[-2:] == ("999", "777")
    else:
        assert state.wire[-1] == "777"


@pytest.mark.asyncio
async def test_result_and_log_ports_are_resolved_after_close(monkeypatch, harness):
    state = harness
    close = state.client.aclose
    logger = Mock()
    metrics = {"reaper_reclaimed": 40}
    seen = []
    result_port = {
        "corrupt": "v2_mark_corrupt_success",
        "cancel": "normalize_v2_admin_result",
        "reaper": "apply_v2_reaper_result",
    }[state.operation]

    def result(value):
        seen.append((result_port, value))
        return 7 if state.operation == "cancel" else True

    async def new_close():
        await close()
        monkeypatch.setattr(svc, result_port, result)
        monkeypatch.setattr(svc, "logger", logger)
        monkeypatch.setattr(svc, "queue_metrics", metrics)

    monkeypatch.setattr(state.client, "aclose", new_close)
    assert await state.run() == (7 if state.operation == "cancel" else 1)
    assert seen == [(result_port, 1)]
    assert state.metrics["reaper_reclaimed"] == 9
    assert metrics["reaper_reclaimed"] == (41 if state.operation == "reaper" else 40)
    state.logger.info.assert_not_called()
    assert logger.info.call_count == (0 if state.operation == "corrupt" else 1)


@pytest.mark.asyncio
async def test_reaper_normalizes_before_close_and_keeps_normalized_value(monkeypatch):
    state = AdminHarness(monkeypatch, "reaper")
    state.raw = "3"
    close = state.client.aclose
    seen = []

    def normalize(value):
        assert state.close_count == 0
        seen.append(value)
        return 7

    async def new_close():
        await close()
        monkeypatch.setattr(svc, "normalize_v2_reaper_result", lambda value: 99)

    monkeypatch.setattr(svc, "normalize_v2_reaper_result", normalize)
    monkeypatch.setattr(state.client, "aclose", new_close)
    assert await state.run() == 7
    assert seen == ["3"] and state.metrics["reaper_reclaimed"] == 16


@pytest.mark.asyncio
async def test_reaper_zero_coercion_still_precedes_normalizer(monkeypatch):
    state = AdminHarness(monkeypatch, "reaper")
    seen = []

    def normalize(value):
        seen.append(value)
        return 0

    monkeypatch.setattr(svc, "normalize_v2_reaper_result", normalize)
    for value in (None, "", [], False):
        state.raw = value
        assert await state.run() == 0
    assert seen == [0, 0, 0, 0]
    assert all(type(value) is int for value in seen)


@pytest.mark.asyncio
async def test_cancel_reason_callback_is_resolved_after_script_loading(monkeypatch):
    state = AdminHarness(monkeypatch, "cancel")
    load = state.queue._load_scripts

    async def new_load(client):
        await load(client)
        monkeypatch.setattr(
            svc, "v2_cancel_reason", lambda reason: "replacement-reason"
        )

    monkeypatch.setattr(state.queue, "_load_scripts", new_load)
    assert await state.run() == 1
    assert state.wire[-2] == "replacement-reason"


@pytest.mark.asyncio
async def test_actual_cancel_during_successful_close_stops_result_processing(
    monkeypatch, harness
):
    entered = asyncio.Event()
    finalized = []

    async def close():
        harness.close_count += 1
        entered.set()
        try:
            await asyncio.Future()
        finally:
            finalized.append(True)

    monkeypatch.setattr(harness.client, "aclose", close)
    task = asyncio.create_task(harness.run())
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        task.cancel("normal-close-cancel")
        with pytest.raises(asyncio.CancelledError) as caught:
            await asyncio.wait_for(task, timeout=2)
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert caught.value.args == ("normal-close-cancel",)
    assert harness.close_count == 1 and finalized == [True]
    assert harness.metrics["reaper_reclaimed"] == 9
    harness.logger.info.assert_not_called()
    harness.logger.warning.assert_not_called()
