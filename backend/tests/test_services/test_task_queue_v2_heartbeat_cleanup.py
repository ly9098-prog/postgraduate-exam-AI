"""Failing regression cases for script-client release after interrupted work."""

import asyncio

import pytest
from redis import exceptions as redis_exc

from tests.queue_heartbeat_support import HeartbeatHarness


@pytest.fixture
def harness(monkeypatch):
    return HeartbeatHarness(monkeypatch)


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["load", "eval"])
@pytest.mark.parametrize(
    "error_type",
    [
        redis_exc.ConnectionError,
        redis_exc.TimeoutError,
        redis_exc.ResponseError,
        RuntimeError,
        asyncio.CancelledError,
    ],
)
async def test_acquired_client_is_closed_once_after_execution_failure(
    harness, stage, error_type
):
    error = error_type("primary heartbeat failure")
    harness.errors[stage] = error
    with pytest.raises(error_type) as caught:
        await harness.run()
    assert caught.value is error
    assert harness.close_count == 1 and harness.close_finished
    assert harness.trace == [
        "get",
        "load",
        *(["eval"] if stage == "eval" else []),
        "close",
    ]
    assert harness.task.lease_expires_at == 20
    assert harness.metrics["owner_fencing_rejected"] == 9
    harness.logger.warning.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["load", "eval"])
@pytest.mark.parametrize(
    "primary_type", [RuntimeError, redis_exc.TimeoutError, asyncio.CancelledError]
)
@pytest.mark.parametrize(
    "cleanup_type", [RuntimeError, redis_exc.TimeoutError, asyncio.CancelledError]
)
async def test_cleanup_failure_does_not_replace_primary(
    harness, stage, primary_type, cleanup_type
):
    primary = primary_type("primary")
    cleanup = cleanup_type("cleanup-detail-must-not-leak")
    harness.errors.update({stage: primary, "close": cleanup})
    with pytest.raises(primary_type) as caught:
        await harness.run()
    assert caught.value is primary and harness.close_count == 1
    assert harness.trace[-1] == "close"
    assert primary.__notes__ == [
        f"v2 heartbeat cleanup also failed ({cleanup_type.__name__})",
    ]
    assert "cleanup-detail-must-not-leak" not in str(primary.__notes__)
    assert harness.task.lease_expires_at == 20
    assert harness.metrics["owner_fencing_rejected"] == 9


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stage", ["_get_script_client", "_load_scripts", "_evalsha_or_reload"]
)
async def test_actual_task_cancel_releases_only_an_acquired_client(
    monkeypatch, harness, stage
):
    entered = asyncio.Event()
    finalized = []

    async def pending(*args):
        entered.set()
        try:
            await asyncio.Future()
        finally:
            finalized.append(True)

    monkeypatch.setattr(harness.queue, stage, pending)
    task = asyncio.create_task(harness.run())
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        task.cancel("operation-cancel")
        with pytest.raises(asyncio.CancelledError) as caught:
            await asyncio.wait_for(task, timeout=2)
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert caught.value.args == ("operation-cancel",)
    assert finalized == [True] and task.cancelled()
    assert harness.close_count == (0 if stage == "_get_script_client" else 1)
    assert harness.task.lease_expires_at == 20
    assert harness.metrics["owner_fencing_rejected"] == 9


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["_load_scripts", "_evalsha_or_reload"])
async def test_actual_cancellation_survives_cleanup_error(monkeypatch, harness, stage):
    entered = asyncio.Event()
    harness.errors["close"] = RuntimeError("cleanup failure")

    async def pending(*args):
        entered.set()
        await asyncio.Future()

    monkeypatch.setattr(harness.queue, stage, pending)
    task = asyncio.create_task(harness.run())
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        task.cancel("primary-cancel")
        with pytest.raises(asyncio.CancelledError) as caught:
            await asyncio.wait_for(task, timeout=2)
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert caught.value.args == ("primary-cancel",)
    assert harness.close_count == 1 and task.cancelled()
    assert caught.value.__notes__ == ["v2 heartbeat cleanup also failed (RuntimeError)"]


@pytest.mark.asyncio
async def test_second_cancellation_during_cleanup_keeps_first_cancellation(
    monkeypatch, harness
):
    operation_entered, close_entered = asyncio.Event(), asyncio.Event()
    close_finalized = []

    async def pending(*args):
        operation_entered.set()
        await asyncio.Future()

    async def close():
        harness.close_count += 1
        close_entered.set()
        try:
            await asyncio.Future()
        finally:
            close_finalized.append(True)

    monkeypatch.setattr(harness.queue, "_load_scripts", pending)
    monkeypatch.setattr(harness.client, "aclose", close)
    task = asyncio.create_task(harness.run())
    try:
        await asyncio.wait_for(operation_entered.wait(), timeout=2)
        task.cancel("first-cancel")
        await asyncio.wait_for(close_entered.wait(), timeout=2)
        task.cancel("second-cancel")
        with pytest.raises(asyncio.CancelledError) as caught:
            await asyncio.wait_for(task, timeout=2)
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert caught.value.args == ("first-cancel",) and task.cancelled()
    assert caught.value.__notes__ == [
        "v2 heartbeat cleanup also failed (CancelledError)"
    ]
    assert harness.close_count == 1 and close_finalized == [True]
    assert harness.task.lease_expires_at == 20


@pytest.mark.asyncio
async def test_diagnostic_note_failure_does_not_replace_primary(harness):
    primary = RuntimeError("primary")
    primary.__notes__ = 42
    harness.errors.update({"load": primary, "close": RuntimeError("cleanup")})
    with pytest.raises(RuntimeError) as caught:
        await harness.run()
    assert caught.value is primary and primary.__notes__ == 42
    assert harness.close_count == 1
