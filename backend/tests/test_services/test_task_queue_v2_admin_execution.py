"""Characterize administrative wire protocol, result order and error policy."""

import asyncio

import pytest
from redis import exceptions as redis_exc

from tests.queue_admin_support import AdminHarness


@pytest.fixture(params=["corrupt", "cancel", "reaper"])
def harness(monkeypatch, request):
    return AdminHarness(monkeypatch, request.param)


def expected_wire(state):
    prefix = (state.client,)
    if state.operation == "corrupt":
        return prefix + (
            "_lua_mark_corrupt_v2",
            5,
            "taskq:v2:processing:demo",
            "taskq:v2:corrupt:demo",
            "taskq:v2:task",
            "taskq:v2:heartbeat",
            "taskq:v2:fencing",
            "task-1",
            "bad-payload",
            "123",
            "211",
        )
    if state.operation == "cancel":
        return prefix + (
            "_lua_cancel_v2",
            7,
            "taskq:v2:ready:demo",
            "taskq:v2:processing:demo",
            "taskq:v2:retry:demo",
            "taskq:v2:dead:demo",
            "taskq:v2:heartbeat",
            "taskq:v2:task",
            "taskq:v2:fencing",
            "task-1",
            "x" * 200,
            "211",
        )
    return prefix + (
        "_lua_reaper_v2",
        6,
        "taskq:v2:processing:demo",
        "taskq:v2:ready:demo",
        "taskq:v2:heartbeat",
        "taskq:v2:task",
        "taskq:v2:corrupt:demo",
        "taskq:v2:fencing",
        "100",
        "124",
        "123",
        "212",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [None, 0, 1, 2, 3, 4, -1, True, "0", "1", b"2"])
async def test_wire_results_and_effect_order(harness, raw):
    state = harness
    state.raw = raw
    result = await state.run()
    expected = bool(raw) if state.operation == "corrupt" else int(raw or 0)
    assert result == expected and type(result) is type(expected)
    assert state.wire == expected_wire(state)
    assert state.close_count == 1 and state.close_finished
    events = ["get", "load"]
    if state.operation == "cancel":
        events.append("v2_cancel_reason")
    events.append("eval")
    if state.operation == "reaper":
        events.append("normalize_v2_reaper_result")
    events.append("close")
    if state.operation == "corrupt":
        events.append("v2_mark_corrupt_success")
    elif state.operation == "cancel":
        events.extend(["normalize_v2_admin_result", "should_log_v2_cancel"])
    else:
        events.append("apply_v2_reaper_result")
    logged = state.operation != "corrupt" and result > 0
    if logged:
        events.append("info")
    assert state.trace == events
    assert state.metrics == {
        "reaper_reclaimed": 9
        + (result if state.operation == "reaper" and result > 0 else 0),
        "owner_fencing_rejected": 17,
    }
    state.logger.warning.assert_not_called()
    if logged:
        message = (
            "v2 Cancel (code=%d): task_id=%s type=%s"
            if state.operation == "cancel"
            else "v2 Reclaimed %d expired tasks for %s"
        )
        args = (
            (result, "task-1", "demo")
            if state.operation == "cancel"
            else (result, "demo")
        )
        state.logger.info.assert_called_once_with(message, *args)
    else:
        state.logger.info.assert_not_called()


@pytest.mark.asyncio
async def test_disabled_and_missing_client_are_quiet(harness):
    harness.queue._redis_enabled = False
    result = await harness.run()
    assert result == 0 and harness.trace == []
    harness.queue._redis_enabled = True
    harness.available = False
    result = await harness.run()
    assert result == 0 and harness.trace == ["get"]
    assert harness.close_count == 0
    harness.logger.warning.assert_not_called()
    harness.logger.info.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["get", "load", "eval", "close", "result"])
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
async def test_ordinary_failure_is_logged_and_cancel_propagates(
    harness, stage, error_type
):
    state = harness
    error = error_type("synthetic admin failure")
    if stage == "result":
        stage = {
            "corrupt": "v2_mark_corrupt_success",
            "cancel": "normalize_v2_admin_result",
            "reaper": "apply_v2_reaper_result",
        }[state.operation]
    state.errors[stage] = error
    if error_type is asyncio.CancelledError:
        with pytest.raises(asyncio.CancelledError) as caught:
            await state.run()
        assert caught.value is error
        state.logger.warning.assert_not_called()
    else:
        result = await state.run()
        assert result == 0
        assert state.logger.warning.call_args.args == (
            ("v2 Reclaim failed for %s: %s", "demo", error)
            if state.operation == "reaper"
            else (
                "v2 Mark corrupt error: %s"
                if state.operation == "corrupt"
                else "v2 Cancel error: %s",
                error,
            )
        )
    assert state.metrics["reaper_reclaimed"] == 9
    state.logger.info.assert_not_called()
    if stage == "get":
        assert state.close_count == 0 and state.wire is None
    if stage == "close":
        assert state.close_count == 1


@pytest.mark.asyncio
async def test_reaper_info_failure_does_not_increment_metric(monkeypatch):
    state = AdminHarness(monkeypatch, "reaper")
    state.errors["info"] = RuntimeError("logging failed")
    assert await state.run() == 0
    assert state.close_count == 1 and state.close_finished
    assert state.metrics["reaper_reclaimed"] == 9
    assert state.logger.warning.call_args.args[-1] is state.errors["info"]


@pytest.mark.asyncio
async def test_corrupt_summary_is_not_truncated_and_cancel_reason_is(monkeypatch):
    state = AdminHarness(monkeypatch, "corrupt")
    summary = "detail" * 100
    assert await state.queue.mark_corrupt_v2("task-1", "demo", summary) is True
    assert state.wire[-3] is summary
