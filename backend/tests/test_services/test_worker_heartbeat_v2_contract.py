"""Contracts for the v2 heartbeat loop with lease-window failure detection."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
import redis.exceptions as redis_exc

from app.services import task_queue_worker as worker
from app.services.task_queue_contract import Task

NOW = 1000.0


class Ports:
    def __init__(self):
        self.events = []
        self.logs = []
        self.metrics = {"lease_renewal_failure": 0}
        self.sleeps = []
        self.heartbeat_calls = []
        self.get_task_calls = []
        self.heartbeat_outcomes = []
        self.cancel_outcomes = []
        self.sleep_policy = None
        self.owner_lost = None
        self.task = None


@pytest.fixture
def ports(monkeypatch):
    ports = Ports()

    def record(kind):
        def fn(*args, **kwargs):
            ports.logs.append((kind, args))

        return fn

    monkeypatch.setattr(
        worker,
        "logger",
        SimpleNamespace(
            info=record("info"),
            warning=record("warning"),
            error=record("error"),
        ),
    )
    monkeypatch.setattr(worker, "queue_metrics", ports.metrics)
    monkeypatch.setattr(worker, "_v2_worker_running", True)

    class Queue:
        async def heartbeat_v2(self, task, lease_sec=0):
            ports.heartbeat_calls.append((task.task_id, lease_sec))
            outcome = ports.heartbeat_outcomes.pop(0) if ports.heartbeat_outcomes else 1
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

        async def get_task_v2(self, task_id):
            ports.get_task_calls.append(task_id)
            outcome = ports.cancel_outcomes.pop(0) if ports.cancel_outcomes else {}
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

    monkeypatch.setattr(worker, "task_queue", Queue())

    async def fake_sleep(seconds):
        ports.sleeps.append(seconds)
        await asyncio.sleep(0)
        if ports.sleep_policy is not None and ports.sleep_policy(
            len(ports.sleeps), seconds
        ):
            worker._v2_worker_running = False
        if len(ports.sleeps) >= 50:
            worker._v2_worker_running = False

    monkeypatch.setattr(
        worker,
        "asyncio",
        SimpleNamespace(
            sleep=fake_sleep,
            CancelledError=asyncio.CancelledError,
        ),
    )
    monkeypatch.setattr(worker, "time", SimpleNamespace(time=lambda: NOW))
    return ports


def make_task(lease_remaining):
    return Task(
        task_id="task-1",
        task_type="t1",
        payload={},
        lease_expires_at=NOW + lease_remaining,
    )


def log_kinds(ports):
    return [entry[0] for entry in ports.logs]


def messages(ports, kind):
    return [entry[1][0] for entry in ports.logs if entry[0] == kind]


@pytest.mark.asyncio
async def test_success_heartbeat_sleeps_interval_and_skips_cancel_flag(ports):
    task = make_task(600)
    ports.task = task
    owner_lost = asyncio.Event()
    ports.sleep_policy = lambda count, seconds: count == 2

    await worker._v2_heartbeat_loop_with_lease_window(task, 60, owner_lost)

    assert ports.heartbeat_calls == [("task-1", 60), ("task-1", 60)]
    assert ports.get_task_calls == ["task-1", "task-1"]
    assert ports.sleeps == [20, 20]
    assert ports.metrics == {"lease_renewal_failure": 0}
    assert owner_lost.is_set() is False
    assert ports.logs == []


@pytest.mark.asyncio
async def test_cancel_requested_stops_without_sleep(ports):
    task = make_task(600)
    owner_lost = asyncio.Event()
    ports.cancel_outcomes = [{"cancel_requested": "1", "cancel_reason": "operator"}]

    await worker._v2_heartbeat_loop_with_lease_window(task, 60, owner_lost)

    assert ports.sleeps == []
    assert owner_lost.is_set() is True
    assert ports.metrics == {"lease_renewal_failure": 0}
    assert messages(ports, "warning") == [
        "v2 Cancel requested, stopping: task_id=%s reason=%s"
    ]
    assert ports.logs[0][1] == (
        "v2 Cancel requested, stopping: task_id=%s reason=%s",
        "task-1",
        "operator",
    )


@pytest.mark.asyncio
async def test_cancel_flag_read_failure_is_non_fatal(ports):
    task = make_task(600)
    owner_lost = asyncio.Event()
    ports.cancel_outcomes = [RuntimeError("hash read failed")]
    ports.sleep_policy = lambda count, seconds: count == 1

    await worker._v2_heartbeat_loop_with_lease_window(task, 60, owner_lost)

    assert ports.sleeps == [20]
    assert owner_lost.is_set() is False
    assert ports.metrics == {"lease_renewal_failure": 0}
    assert ports.logs == []


@pytest.mark.asyncio
async def test_cancel_without_reason_defaults_to_empty_string(ports):
    task = make_task(600)
    owner_lost = asyncio.Event()
    ports.cancel_outcomes = [{"cancel_requested": "1"}]

    await worker._v2_heartbeat_loop_with_lease_window(task, 60, owner_lost)

    assert ports.sleeps == []
    assert owner_lost.is_set() is True
    assert ports.logs[0][1] == (
        "v2 Cancel requested, stopping: task_id=%s reason=%s",
        "task-1",
        "",
    )


@pytest.mark.asyncio
async def test_missing_task_hash_is_non_fatal(ports):
    task = make_task(600)
    owner_lost = asyncio.Event()
    ports.cancel_outcomes = [None]
    ports.sleep_policy = lambda count, seconds: count == 1

    await worker._v2_heartbeat_loop_with_lease_window(task, 60, owner_lost)

    assert ports.sleeps == [20]
    assert owner_lost.is_set() is False
    assert ports.metrics == {"lease_renewal_failure": 0}
    assert ports.logs == []


@pytest.mark.asyncio
async def test_explicit_rejection_marks_owner_lost(ports):
    task = make_task(600)
    owner_lost = asyncio.Event()
    ports.heartbeat_outcomes = [0]

    await worker._v2_heartbeat_loop_with_lease_window(task, 60, owner_lost)

    assert ports.sleeps == []
    assert owner_lost.is_set() is True
    assert ports.metrics == {"lease_renewal_failure": 1}
    assert ports.logs == [
        (
            "warning",
            (
                "v2 Heartbeat rejected (code=%d), owner lost: task_id=%s",
                0,
                "task-1",
            ),
        )
    ]


@pytest.mark.asyncio
async def test_transient_error_with_short_lease_window_marks_owner_lost(ports):
    task = make_task(15)
    owner_lost = asyncio.Event()
    ports.heartbeat_outcomes = [redis_exc.ConnectionError("boom")]

    await worker._v2_heartbeat_loop_with_lease_window(task, 60, owner_lost)

    assert ports.sleeps == []
    assert owner_lost.is_set() is True
    assert ports.metrics == {"lease_renewal_failure": 1}
    assert messages(ports, "warning") == [
        "v2 Heartbeat transient error + short lease window (%.1fs < %ds), "
        "owner lost: task_id=%s error=%s"
    ]
    assert ports.logs[0][1][1] == 15.0
    assert ports.logs[0][1][2] == 40


@pytest.mark.asyncio
async def test_transient_error_with_safe_window_retries_once(ports):
    task = make_task(600)
    owner_lost = asyncio.Event()
    ports.heartbeat_outcomes = [redis_exc.TimeoutError("slow"), 1]
    ports.sleep_policy = lambda count, seconds: count == 2

    await worker._v2_heartbeat_loop_with_lease_window(task, 60, owner_lost)

    assert ports.heartbeat_calls == [("task-1", 60), ("task-1", 60)]
    assert ports.sleeps == [1, 20]
    assert owner_lost.is_set() is False
    assert ports.metrics == {"lease_renewal_failure": 0}
    assert messages(ports, "warning") == [
        "v2 Heartbeat transient error, retrying once: task_id=%s error=%s"
    ]


@pytest.mark.asyncio
async def test_transient_error_retry_recovery_keeps_heartbeat_loop_running(ports):
    task = make_task(600)
    owner_lost = asyncio.Event()
    ports.heartbeat_outcomes = [redis_exc.TimeoutError("slow"), 1]
    ports.sleep_policy = lambda count, seconds: count == 3

    await worker._v2_heartbeat_loop_with_lease_window(task, 60, owner_lost)

    assert ports.heartbeat_calls == [("task-1", 60), ("task-1", 60), ("task-1", 60)]
    assert ports.sleeps == [1, 20, 20]
    assert owner_lost.is_set() is False
    assert ports.metrics == {"lease_renewal_failure": 0}


@pytest.mark.asyncio
async def test_transient_error_retry_rejected_marks_owner_lost(ports):
    task = make_task(600)
    owner_lost = asyncio.Event()
    ports.heartbeat_outcomes = [redis_exc.ConnectionError("boom"), 0]

    await worker._v2_heartbeat_loop_with_lease_window(task, 60, owner_lost)

    assert ports.sleeps == [1]
    assert owner_lost.is_set() is True
    assert ports.metrics == {"lease_renewal_failure": 1}
    assert messages(ports, "warning")[-1] == (
        "v2 Heartbeat retry failed, owner lost: task_id=%s"
    )


@pytest.mark.asyncio
async def test_transient_error_retry_exception_marks_owner_lost(ports):
    task = make_task(600)
    owner_lost = asyncio.Event()
    ports.heartbeat_outcomes = [redis_exc.ConnectionError("boom"), ValueError("x")]

    await worker._v2_heartbeat_loop_with_lease_window(task, 60, owner_lost)

    assert ports.sleeps == [1]
    assert owner_lost.is_set() is True
    assert ports.metrics == {"lease_renewal_failure": 1}
    assert messages(ports, "warning")[-1] == (
        "v2 Heartbeat retry failed, owner lost: task_id=%s"
    )


@pytest.mark.asyncio
async def test_unexpected_error_marks_owner_lost(ports):
    task = make_task(600)
    owner_lost = asyncio.Event()
    ports.heartbeat_outcomes = [ValueError("weird")]

    await worker._v2_heartbeat_loop_with_lease_window(task, 60, owner_lost)

    assert owner_lost.is_set() is True
    assert ports.metrics == {"lease_renewal_failure": 1}
    assert messages(ports, "warning") == [
        "v2 Heartbeat unexpected error, owner lost: task_id=%s error=%s"
    ]


@pytest.mark.asyncio
async def test_cancellation_breaks_without_side_effects(ports):
    task = make_task(600)
    owner_lost = asyncio.Event()
    ports.heartbeat_outcomes = [asyncio.CancelledError()]

    await worker._v2_heartbeat_loop_with_lease_window(task, 60, owner_lost)

    assert ports.sleeps == []
    assert owner_lost.is_set() is False
    assert ports.metrics == {"lease_renewal_failure": 0}
    assert ports.logs == []


@pytest.mark.asyncio
async def test_rejection_without_owner_event_still_breaks(ports):
    task = make_task(600)
    ports.heartbeat_outcomes = [0]

    await worker._v2_heartbeat_loop_with_lease_window(task, 60, None)

    assert ports.metrics == {"lease_renewal_failure": 1}
    assert log_kinds(ports) == ["warning"]
