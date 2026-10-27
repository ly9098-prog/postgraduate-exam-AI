"""Characterize terminal transitions and real asyncio child lifetimes."""

import asyncio

import pytest
import pytest_asyncio

from app.core import log_context
from app.services import task_queue_worker as worker
from app.services.db_fencing import FencingRejectedError
from tests.worker_claimed_support import CREATE_TASK, WAIT_FOR, ClaimedHarness


@pytest_asyncio.fixture
async def harness(monkeypatch):
    outer = log_context._log_context_var.set({"user_id": "outer"})
    state = ClaimedHarness(monkeypatch)
    try:
        yield state
    finally:
        await state.dispose()
        log_context._log_context_var.reset(outer)


def assert_stopped(state):
    assert len(state.children) == 3 and all(task.done() for task in state.children)
    assert state.sem.releases == state.sem.slot._value == 1
    assert state.events[-2:] == ["reset", "release"]
    assert log_context.get_log_context() == {"user_id": "outer"}


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [1, 0, -1, 2, None, False])
async def test_completion_codes_keep_heartbeat_alive_through_transition(harness, code):
    harness.code = code
    assert await harness.run() is None
    args, kwargs = harness.call("complete")
    assert args[0].task_id == "claimed-task" and kwargs["heartbeat_alive"]
    assert "fail" not in harness.events
    assert harness.metrics == {
        "owner_fencing_rejected": int(code in (0, -1)),
        "hard_deadline_exceeded": 0,
    }
    assert_stopped(harness)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload,pipeline_id",
    [
        ({}, "claimed-task"),
        ({"pipeline_id": "pipeline", "job_id": "job"}, "pipeline"),
        ({"pipeline_id": "", "job_id": 12}, "12"),
        ({"pipeline_id": 0}, "claimed-task"),
    ],
)
@pytest.mark.parametrize("explicit_ids", [False, True])
async def test_log_identity_fallback_and_child_context(
    harness, payload, pipeline_id, explicit_ids
):
    task = harness.task(payload)
    if explicit_ids:
        task.trace_id, task.request_id = "explicit-trace", "explicit-request"
    await harness.run(task)
    kwargs = harness.call("bind")[1]
    assert kwargs == dict(
        trace_id="explicit-trace" if explicit_ids else "made-tr_job",
        request_id="explicit-request" if explicit_ids else "made-req_job",
        job_id="claimed-task",
        pipeline_id=pipeline_id,
    )
    assert ("trace_id" in harness.events) == (not explicit_ids)
    assert ("request_id" in harness.events) == (not explicit_ids)
    context = harness.call("process")[1]["context"]
    assert context == {"user_id": "outer", **kwargs}
    assert_stopped(harness)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error_type", [RuntimeError, FencingRejectedError, asyncio.CancelledError]
)
@pytest.mark.parametrize("owner_lost", [False, True])
async def test_business_error_owner_loss_and_fencing_policy(
    harness, error_type, owner_lost
):
    error = error_type("synthetic business failure")
    harness.faults["process.result"] = error
    harness.mode = "error-and-lose" if owner_lost else "success"
    await harness.run()
    rejected = (
        error_type in {FencingRejectedError, asyncio.CancelledError} or owner_lost
    )
    assert harness.metrics["owner_fencing_rejected"] == int(rejected)
    assert ("fail" in harness.events) == (not rejected)
    assert "complete" not in harness.events
    if not rejected:
        args, kwargs = harness.call("fail")
        assert args[1] == str(error) and kwargs["heartbeat_alive"]
    assert_stopped(harness)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["owner-lost", "finish-and-lose"])
async def test_owner_loss_prevents_terminal_conversion(harness, mode):
    harness.mode = mode
    await WAIT_FOR(harness.run(), 1)
    assert "complete" not in harness.events and "fail" not in harness.events
    assert harness.owner_event.is_set()
    assert harness.metrics["owner_fencing_rejected"] == int(mode == "owner-lost")
    assert_stopped(harness)


@pytest.mark.asyncio
@pytest.mark.parametrize("transition", ["complete", "fail"])
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_transition_ordinary_error_warns_but_cancel_propagates(
    harness, transition, error_type
):
    if transition == "fail":
        harness.faults["process.result"] = ValueError("business")
    error = error_type("synthetic terminal failure")
    harness.faults[transition] = error
    if error_type is asyncio.CancelledError:
        with pytest.raises(asyncio.CancelledError) as caught:
            await harness.run()
        assert caught.value is error
    else:
        await harness.run()
        assert harness.logger.warning.called
    assert harness.events.count(transition) == 1
    assert_stopped(harness)


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_error", [None, RuntimeError, asyncio.CancelledError])
async def test_real_hard_deadline_fails_once_then_skips_completion(
    monkeypatch, harness, fail_error
):
    harness.mode = "deadline"
    monkeypatch.setattr(worker, "_PROCESS_HARD_DEADLINE_SEC", 0.01)
    if fail_error:
        harness.faults["fail"] = fail_error("deadline transition failure")
    if fail_error is asyncio.CancelledError:
        with pytest.raises(asyncio.CancelledError):
            await harness.run()
    else:
        await harness.run()
    assert harness.children[1].cancelled()
    assert harness.call("fail")[0][1] == "hard wall-clock deadline exceeded"
    assert harness.call("fail")[1]["heartbeat_alive"]
    assert harness.events.count("fail") == 1 and "complete" not in harness.events
    assert harness.metrics == {"owner_fencing_rejected": 0, "hard_deadline_exceeded": 1}
    assert_stopped(harness)


@pytest.mark.asyncio
async def test_outer_cancel_during_business_retains_current_owner_loss_policy(harness):
    harness.mode = "blocked"
    parent = CREATE_TASK(harness.run())
    try:
        await WAIT_FOR(harness.started.wait(), 1)
        parent.cancel("drain-cancel")
        assert await parent is None
    finally:
        if not parent.done():
            parent.cancel()
            await asyncio.gather(parent, return_exceptions=True)
    assert not parent.cancelled()
    assert harness.metrics["owner_fencing_rejected"] == 1
    assert "complete" not in harness.events and "fail" not in harness.events
    assert_stopped(harness)


@pytest.mark.asyncio
@pytest.mark.parametrize("transition", ["complete", "fail"])
async def test_outer_cancel_during_terminal_transition_propagates(harness, transition):
    harness.mode = f"{transition}-blocked"
    if transition == "fail":
        harness.faults["process.result"] = ValueError("business")
    parent = CREATE_TASK(harness.run())
    started = (
        harness.complete_started if transition == "complete" else harness.fail_started
    )
    try:
        await WAIT_FOR(started.wait(), 1)
        parent.cancel("terminal-cancel")
        with pytest.raises(asyncio.CancelledError, match="terminal-cancel"):
            await parent
    finally:
        if not parent.done():
            parent.cancel()
            await asyncio.gather(parent, return_exceptions=True)
    assert_stopped(harness)


@pytest.mark.asyncio
async def test_error_summary_keeps_original_500_character_limit(harness):
    harness.faults["process.result"] = ValueError("x" * 600)
    await harness.run()
    assert harness.call("fail")[0][1] == "x" * 500
    assert_stopped(harness)
