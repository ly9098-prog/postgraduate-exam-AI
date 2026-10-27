"""Regression coverage for startup, slot release and terminal classification."""

import asyncio
import json

import pytest
import pytest_asyncio

from app.core import log_context
from app.services import task_queue_worker as worker
from app.services.task_queue_v2_claim_contract import build_v2_claimed_task
from tests.worker_claimed_support import ClaimedHarness


@pytest_asyncio.fixture
async def harness(monkeypatch):
    outer = log_context._log_context_var.set({"user_id": "outer"})
    state = ClaimedHarness(monkeypatch)
    try:
        yield state
    finally:
        await state.dispose()
        log_context._log_context_var.reset(outer)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [None, [], 7, "invalid"])
async def test_invalid_claim_payload_still_releases_the_owned_slot(harness, payload):
    task = harness.task()
    task.payload = payload
    with pytest.raises(AttributeError):
        await harness.run(task)
    assert harness.sem.releases == harness.sem.slot._value == 1
    assert harness.events == ["release"]
    assert log_context.get_log_context() == {"user_id": "outer"}


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["trace_id", "request_id", "bind"])
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_log_preparation_failure_releases_slot_without_spawning(
    harness, stage, error_type
):
    error = error_type("synthetic preparation failure")
    harness.faults[stage] = error
    with pytest.raises(error_type) as caught:
        await harness.run()
    assert caught.value is error
    assert harness.sem.releases == harness.sem.slot._value == 1
    assert not harness.children and not harness.coroutines
    assert "reset" not in harness.events
    assert log_context.get_log_context() == {"user_id": "outer"}


@pytest.mark.asyncio
@pytest.mark.parametrize("number", [1, 2, 3])
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_partial_child_startup_is_reaped_and_unsubmitted_coroutine_closed(
    harness, number, error_type
):
    harness.fail_spawn = number
    harness.spawn_error = error_type("synthetic task factory failure")
    with pytest.raises(error_type) as caught:
        await harness.run()
    assert caught.value is harness.spawn_error
    assert len(harness.children) == number - 1
    assert all(child.done() for child in harness.children)
    assert harness.coroutines[-1].cr_frame is None
    assert harness.sem.releases == harness.sem.slot._value == 1
    assert harness.events[-2:] == ["reset", "release"]
    assert log_context.get_log_context() == {"user_id": "outer"}


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_log_reset_failure_cannot_skip_slot_release(harness, error_type):
    error = error_type("private-reset-detail")
    harness.faults["reset"] = error
    with pytest.raises(error_type) as caught:
        await harness.run()
    assert caught.value is error
    assert harness.sem.releases == harness.sem.slot._value == 1
    assert all(child.done() for child in harness.children)
    assert harness.events[-2:] == ["reset", "release"]


@pytest.mark.asyncio
@pytest.mark.parametrize("transition", ["complete", "fail"])
@pytest.mark.parametrize("cleanup_type", [RuntimeError, asyncio.CancelledError])
async def test_reset_failure_preserves_primary_terminal_cancel(
    harness, transition, cleanup_type
):
    primary = asyncio.CancelledError("primary-terminal-cancel")
    harness.faults[transition] = primary
    harness.faults["reset"] = cleanup_type("private-reset-detail")
    if transition == "fail":
        harness.faults["process.result"] = ValueError("business")
    with pytest.raises(asyncio.CancelledError) as caught:
        await harness.run()
    assert caught.value is primary
    assert harness.sem.releases == harness.sem.slot._value == 1
    assert all(child.done() for child in harness.children)
    assert "private-reset-detail" not in str(primary.__notes__)
    assert cleanup_type.__name__ in primary.__notes__[-1]


@pytest.mark.asyncio
@pytest.mark.parametrize("owner_lost", [False, True])
async def test_business_timeout_is_not_a_hard_deadline_or_followed_by_complete(
    harness, owner_lost
):
    error = TimeoutError("synthetic provider timeout")
    harness.faults["process.result"] = error
    harness.mode = "error-and-lose" if owner_lost else "success"
    await harness.run()
    assert harness.metrics == {
        "owner_fencing_rejected": int(owner_lost),
        "hard_deadline_exceeded": 0,
    }
    assert harness.events.count("fail") == int(not owner_lost)
    assert "complete" not in harness.events
    if not owner_lost:
        assert harness.call("fail")[0][1] == str(error)
    assert harness.sem.releases == harness.sem.slot._value == 1
    assert all(child.done() for child in harness.children)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [None, []])
async def test_actual_claim_adapter_can_reach_payload_preparation_failure(
    harness, payload
):
    result = build_v2_claimed_task(
        [
            "claimed-task",
            json.dumps(
                {
                    "task_id": "claimed-task",
                    "task_type": "answer_projection",
                    "payload": payload,
                }
            ),
            "claimed-owner",
            "8",
            "1000",
        ],
        task_type="answer_projection",
        owner_token="claimed-owner",
    )
    assert result.corrupt_error is None and result.task is not None
    with pytest.raises(AttributeError):
        await harness.run(result.task)
    assert harness.sem.releases == harness.sem.slot._value == 1
    assert not harness.children and not harness.coroutines


@pytest.mark.asyncio
async def test_broken_secondary_error_notes_cannot_skip_slot_release(harness):
    primary = asyncio.CancelledError("primary-terminal-cancel")
    primary.__notes__ = ()
    harness.faults.update(
        {"complete": primary, "reset": RuntimeError("private-reset-detail")}
    )
    with pytest.raises(asyncio.CancelledError) as caught:
        await harness.run()
    assert caught.value is primary
    assert harness.sem.releases == harness.sem.slot._value == 1
    assert all(child.done() for child in harness.children)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "port",
    [
        "_v2_heartbeat_loop_with_lease_window",
        "_process_task_v2",
        "_cancel_on_owner_loss",
    ],
)
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_child_coroutine_construction_failure_unwinds_prior_children(
    monkeypatch, harness, port, error_type
):
    error = error_type("synthetic child construction failure")

    def broken(*args):
        raise error

    monkeypatch.setattr(worker, port, broken)
    with pytest.raises(error_type) as caught:
        await harness.run()
    assert caught.value is error
    assert all(child.done() for child in harness.children)
    assert harness.sem.releases == harness.sem.slot._value == 1
    assert harness.events[-2:] == ["reset", "release"]
    assert log_context.get_log_context() == {"user_id": "outer"}
