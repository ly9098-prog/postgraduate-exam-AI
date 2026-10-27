"""Pin the live port lookups and lease/identity snapshot boundary."""

import asyncio
from unittest.mock import Mock

import pytest

from app.services import task_queue_service as svc
from tests.queue_heartbeat_support import HeartbeatHarness


@pytest.fixture
def harness(monkeypatch):
    return HeartbeatHarness(monkeypatch)


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [0, 1])
async def test_result_ports_are_resolved_after_close(monkeypatch, harness, raw):
    state = harness
    state.raw = raw
    new_metrics = {"owner_fencing_rejected": 40}
    new_logger = Mock()
    original_close = state.client.aclose
    original_apply = svc.apply_v2_heartbeat_result
    seen = []

    def mismatch(result):
        seen.append(("mismatch", result))
        return "owner" if result == 0 else None

    def apply(task, **kwargs):
        seen.append(("apply", task, kwargs))
        return original_apply(task, **kwargs)

    async def close():
        await original_close()
        monkeypatch.setattr(svc, "queue_metrics", new_metrics)
        monkeypatch.setattr(svc, "logger", new_logger)
        monkeypatch.setattr(svc, "v2_heartbeat_mismatch", mismatch)
        monkeypatch.setattr(svc, "apply_v2_heartbeat_result", apply)

    monkeypatch.setattr(state.client, "aclose", close)
    assert await state.run(lease_sec=30) == raw
    assert seen[0] == ("mismatch", raw)
    state.logger.warning.assert_not_called()
    assert state.metrics["owner_fencing_rejected"] == 9
    if raw == 0:
        assert new_metrics["owner_fencing_rejected"] == 41
        new_logger.warning.assert_called_once()
        assert len(seen) == 1 and state.task.lease_expires_at == 20
    else:
        new_logger.warning.assert_not_called()
        assert seen[1] == ("apply", state.task, {"result": 1, "lease_sec": 30})
        assert state.task.lease_expires_at == 130.0


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [0, 1])
async def test_identity_is_snapshotted_before_acquisition(monkeypatch, harness, raw):
    state = harness
    state.raw = raw
    original_acquire = state.queue._get_script_client

    async def acquire():
        client = await original_acquire()
        state.task.task_id = "changed-id"
        state.task.task_type = "changed-type"
        state.task.owner_token = "changed-owner"
        state.task.generation = 99
        return client

    monkeypatch.setattr(state.queue, "_get_script_client", acquire)
    assert await state.run(lease_sec=30) == raw
    assert state.wire[3] == "taskq:v2:processing:demo"
    assert state.wire[-3:] == ("heartbeat-test", "30", "owner-1")
    assert state.task.generation == 99 and state.task.task_id == "changed-id"
    assert state.task.lease_expires_at == (130.0 if raw else 20)
    if raw == 0:
        assert state.logger.warning.call_args.args[-1] == "heartbeat-test"


@pytest.mark.asyncio
async def test_queue_methods_and_wire_ports_remain_live(monkeypatch, harness):
    state = harness
    seen = []
    acquire, load, evaluate, close = (
        state.queue._get_script_client,
        state.queue._load_scripts,
        state.queue._evalsha_or_reload,
        state.client.aclose,
    )

    async def new_close():
        seen.append("new-close")
        await close()

    async def new_eval(*args):
        seen.append("new-eval")
        monkeypatch.setattr(state.client, "aclose", new_close)
        return await evaluate(*args)

    async def new_load(client):
        seen.append("new-load")
        monkeypatch.setattr(state.queue, "_evalsha_or_reload", new_eval)
        monkeypatch.setattr(svc, "_v2_p_key", lambda task_type: f"changed:{task_type}")
        monkeypatch.setattr(svc, "_V2_FENCING_PREFIX", "changed:fencing:")
        await load(client)

    async def new_acquire():
        client = await acquire()
        monkeypatch.setattr(state.queue, "_load_scripts", new_load)
        return client

    monkeypatch.setattr(state.queue, "_get_script_client", new_acquire)
    assert await state.run(lease_sec=30) == 1
    assert seen == ["new-load", "new-eval", "new-close"]
    assert state.wire[3] == "changed:demo" and state.wire[6] == "changed:fencing:"


@pytest.mark.asyncio
async def test_cancellation_during_normal_close_prevents_result_updates(
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
        task.cancel("close-cancel")
        with pytest.raises(asyncio.CancelledError) as caught:
            await asyncio.wait_for(task, timeout=2)
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert caught.value.args == ("close-cancel",)
    assert finalized == [True] and harness.close_count == 1
    assert harness.task.lease_expires_at == 20
    assert harness.metrics["owner_fencing_rejected"] == 9
