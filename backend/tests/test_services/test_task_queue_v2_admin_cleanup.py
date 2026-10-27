"""Regression contracts for client release on admin script interruption."""

import asyncio

import pytest
from redis import exceptions as redis_exc

from tests.queue_admin_support import AdminHarness


@pytest.fixture(params=["corrupt", "cancel", "reaper"])
def harness(monkeypatch, request):
    return AdminHarness(monkeypatch, request.param)


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["load", "eval"])
@pytest.mark.parametrize(
    "error_type",
    [
        RuntimeError,
        redis_exc.TimeoutError,
        redis_exc.ResponseError,
        asyncio.CancelledError,
    ],
)
async def test_failed_script_releases_acquired_client(harness, stage, error_type):
    state = harness
    primary = error_type("primary")
    state.errors[stage] = primary
    if error_type is asyncio.CancelledError:
        with pytest.raises(asyncio.CancelledError) as caught:
            await state.run()
        assert caught.value is primary
        state.logger.warning.assert_not_called()
    else:
        assert await state.run() == 0
        assert state.logger.warning.call_args.args[-1] is primary
    assert state.close_count == 1 and state.close_finished
    assert state.trace.index("close") > state.trace.index(stage)
    assert state.metrics == {"reaper_reclaimed": 9, "owner_fencing_rejected": 17}


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["load", "eval"])
@pytest.mark.parametrize("primary_type", [RuntimeError, asyncio.CancelledError])
@pytest.mark.parametrize("cleanup_type", [RuntimeError, asyncio.CancelledError])
async def test_cleanup_failure_keeps_original_policy(
    harness, stage, primary_type, cleanup_type
):
    state = harness
    primary = primary_type("primary")
    state.errors.update(
        {stage: primary, "close": cleanup_type("private-cleanup-detail")}
    )
    if primary_type is asyncio.CancelledError:
        with pytest.raises(asyncio.CancelledError) as caught:
            await state.run()
        assert caught.value is primary
        state.logger.warning.assert_not_called()
    else:
        assert await state.run() == 0
        assert state.logger.warning.call_args.args[-1] is primary
    assert state.close_count == 1
    assert primary.__notes__ == [
        f"v2 admin cleanup also failed ({cleanup_type.__name__})",
    ]
    assert "private-cleanup-detail" not in str(primary.__notes__)
    assert state.metrics["reaper_reclaimed"] == 9


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stage", ["_get_script_client", "_load_scripts", "_evalsha_or_reload"]
)
async def test_actual_task_cancel_closes_only_acquired_client(
    monkeypatch, harness, stage
):
    state = harness
    entered = asyncio.Event()
    finalized = []

    async def pending(*args):
        entered.set()
        try:
            await asyncio.Future()
        finally:
            finalized.append(True)

    monkeypatch.setattr(state.queue, stage, pending)
    task = asyncio.create_task(state.run())
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        task.cancel("admin-cancel")
        with pytest.raises(asyncio.CancelledError) as caught:
            await asyncio.wait_for(task, timeout=2)
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert caught.value.args == ("admin-cancel",) and task.cancelled()
    assert finalized == [True]
    assert state.close_count == (0 if stage == "_get_script_client" else 1)
    state.logger.warning.assert_not_called()
    state.logger.info.assert_not_called()


@pytest.mark.asyncio
async def test_secondary_cancel_during_cleanup_preserves_first(monkeypatch, harness):
    entered, closing = asyncio.Event(), asyncio.Event()
    finalized = []

    async def pending(*args):
        entered.set()
        await asyncio.Future()

    async def close():
        harness.close_count += 1
        closing.set()
        try:
            await asyncio.Future()
        finally:
            finalized.append(True)

    monkeypatch.setattr(harness.queue, "_load_scripts", pending)
    monkeypatch.setattr(harness.client, "aclose", close)
    task = asyncio.create_task(harness.run())
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        task.cancel("primary-cancel")
        await asyncio.wait_for(closing.wait(), timeout=2)
        task.cancel("secondary-cancel")
        with pytest.raises(asyncio.CancelledError) as caught:
            await asyncio.wait_for(task, timeout=2)
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert caught.value.args == ("primary-cancel",) and task.cancelled()
    assert harness.close_count == 1 and finalized == [True]
    assert caught.value.__notes__ == ["v2 admin cleanup also failed (CancelledError)"]


@pytest.mark.asyncio
async def test_corrupt_diagnostic_notes_cannot_override_original_error(harness):
    primary = RuntimeError("primary")
    primary.__notes__ = 42
    harness.errors.update({"load": primary, "close": RuntimeError("cleanup")})
    assert await harness.run() == 0
    assert harness.close_count == 1
    assert harness.logger.warning.call_args.args[-1] is primary


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ["bad-integer", {}])
async def test_reaper_normalization_failure_also_closes(monkeypatch, raw):
    state = AdminHarness(monkeypatch, "reaper")
    # Empty mappings are intentionally coerced to zero before normalization.
    state.raw = raw if raw else {"not": "an-integer"}
    assert await state.run() == 0
    assert state.close_count == 1 and state.close_finished
    assert state.trace == [
        "get",
        "load",
        "eval",
        "normalize_v2_reaper_result",
        "close",
        "warning",
    ]
    assert state.metrics["reaper_reclaimed"] == 9


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,stage",
    [
        ("cancel", "v2_cancel_reason"),
        ("reaper", "normalize_v2_reaper_result"),
    ],
)
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_preclose_callback_failure_also_releases(
    monkeypatch, operation, stage, error_type
):
    state = AdminHarness(monkeypatch, operation)
    primary = error_type("preclose callback")
    state.errors[stage] = primary
    if error_type is asyncio.CancelledError:
        with pytest.raises(asyncio.CancelledError) as caught:
            await state.run()
        assert caught.value is primary
        state.logger.warning.assert_not_called()
    else:
        assert await state.run() == 0
        assert state.logger.warning.call_args.args[-1] is primary
    assert state.close_count == 1 and state.close_finished
    assert state.metrics["reaper_reclaimed"] == 9
