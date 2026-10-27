"""Characterize heartbeat fencing, wire arguments and result ordering."""

import asyncio

import pytest
from redis import exceptions as redis_exc

from tests.queue_heartbeat_support import HeartbeatHarness


@pytest.fixture
def harness(monkeypatch):
    return HeartbeatHarness(monkeypatch)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw,expected",
    [
        (1, 1),
        ("1", 1),
        (b"1", 1),
        (1.75, 1),
        (True, 1),
        (None, 0),
        (0, 0),
        ("0", 0),
        (-1, -1),
        ("-1", -1),
        (2, 2),
        (-2, -2),
    ],
)
@pytest.mark.parametrize("shape", ["task", "tuple"])
async def test_fenced_wire_and_result_contract(harness, raw, expected, shape):
    state = harness
    state.raw = raw
    argument = state.task if shape == "task" else ("heartbeat-test", "demo", "owner-1")
    result = await state.queue.heartbeat_v2(argument, lease_sec=30)
    assert result == expected and type(result) is int
    assert state.wire == (
        state.client,
        "_lua_heartbeat_v2",
        4,
        "taskq:v2:processing:demo",
        "taskq:v2:heartbeat",
        "taskq:v2:task",
        "taskq:v2:fencing",
        "heartbeat-test",
        "30",
        "owner-1",
    )
    assert state.close_count == 1 and state.close_finished
    assert state.task.payload == {"opaque": "kept"} and state.task.generation == 3
    rejected = expected in {0, -1}
    assert state.metrics == {
        "owner_fencing_rejected": 9 + rejected,
        "other": 17,
    }
    assert state.task.lease_expires_at == (
        130.0 if expected == 1 and shape == "task" else 20
    )
    assert state.trace == [
        "get",
        "load",
        "eval",
        "close",
        ("mismatch", expected),
        *(["warning"] if rejected else [("apply", expected, 30)]),
    ]
    if rejected:
        state.logger.warning.assert_called_once_with(
            "v2 Heartbeat %s mismatch: task_id=%s",
            "owner" if expected == 0 else "generation",
            "heartbeat-test",
        )
    else:
        state.logger.warning.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "argument,override",
    [
        ("heartbeat-test", "demo"),
        (("", "demo", "owner"), None),
        (("heartbeat-test", "", "owner"), None),
        (("heartbeat-test", "demo", ""), None),
    ],
)
async def test_invalid_identity_never_acquires_client(harness, argument, override):
    assert await harness.queue.heartbeat_v2(argument, task_type=override) == 0
    assert harness.trace == [] and harness.close_count == 0
    assert harness.metrics["owner_fencing_rejected"] == 9


@pytest.mark.asyncio
async def test_disabled_redis_and_missing_client_do_not_report_fencing_rejection(
    harness,
):
    state = harness
    state.queue._redis_enabled = False
    assert await state.run() == 0 and state.trace == []
    state.queue._redis_enabled = True
    state.available = False
    assert await state.run() == 0 and state.trace == ["get"]
    assert state.close_count == 0 and state.metrics["owner_fencing_rejected"] == 9
    state.logger.warning.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["get", "load", "eval", "close"])
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
async def test_execution_errors_propagate_without_fencing_or_lease_update(
    harness, stage, error_type
):
    state = harness
    error = error_type("synthetic queue error")
    state.errors[stage] = error
    with pytest.raises(error_type) as caught:
        await state.run(lease_sec=30)
    assert caught.value is error
    assert state.task.lease_expires_at == 20
    assert state.metrics["owner_fencing_rejected"] == 9
    assert not any(isinstance(event, tuple) for event in state.trace)
    state.logger.warning.assert_not_called()
    if stage == "get":
        assert state.close_count == 0 and state.wire is None
    if stage == "load":
        assert state.wire is None
    if stage == "close":
        assert state.close_count == 1 and not state.close_finished


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["mismatch", "warning", "apply"])
async def test_result_port_failure_happens_after_close_and_before_state_update(
    harness, stage
):
    state = harness
    state.raw = 0 if stage == "warning" else 1
    error = RuntimeError("synthetic result port")
    state.errors[stage] = error
    with pytest.raises(RuntimeError) as caught:
        await state.run(lease_sec=30)
    assert caught.value is error and state.close_count == 1 and state.close_finished
    assert state.metrics["owner_fencing_rejected"] == 9
    assert state.task.lease_expires_at == 20
    assert state.trace.index("close") < state.trace.index(("mismatch", state.raw))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw,error_type", [("not-an-int", ValueError), ({}, TypeError)]
)
async def test_malformed_lua_result_is_parsed_only_after_closing(
    harness, raw, error_type
):
    harness.raw = raw
    with pytest.raises(error_type):
        await harness.run()
    assert harness.trace == ["get", "load", "eval", "close"]
    assert harness.close_count == 1
    assert harness.task.lease_expires_at == 20


@pytest.mark.asyncio
async def test_tuple_type_override_does_not_remove_owner_fencing(harness):
    assert (
        await harness.queue.heartbeat_v2(
            ("heartbeat-test", "hint", "owner-1"),
            task_type="demo",
            lease_sec=30,
        )
        == 1
    )
    assert harness.wire[3] == "taskq:v2:processing:demo"
    assert harness.wire[-1] == "owner-1"


@pytest.mark.asyncio
@pytest.mark.parametrize("argument", [("only",), ("a", "b"), ("a", "b", "c", "d")])
async def test_malformed_tuple_still_fails_before_disabled_redis_gate(
    harness, argument
):
    harness.queue._redis_enabled = False
    with pytest.raises(ValueError):
        await harness.queue.heartbeat_v2(argument)
    assert harness.trace == []
