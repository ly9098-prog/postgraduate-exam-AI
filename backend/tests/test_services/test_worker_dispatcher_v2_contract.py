"""Contracts for the v2 dispatcher claim, backoff and spawn supervision."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.services import task_queue_worker as worker
from app.services.task_queue_service import TaskQueueUnavailableError


class Ports:
    def __init__(self):
        self.events = []
        self.logs = []
        self.metrics = {"queue_redis_failure": 0}
        self.sleeps = []
        self.claim_calls = []
        self.claim_outcomes = []
        self.processing_calls = []
        self.spawned_names = []
        self.on_acquire = None
        self.stop_on_sleep = None
        self.active_processing_ops = []


def value(task_id="task-1", task_type="t1"):
    return SimpleNamespace(task_id=task_id, task_type=task_type)


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
            critical=record("critical"),
            exception=record("exception"),
        ),
    )
    monkeypatch.setattr(worker, "queue_metrics", ports.metrics)
    monkeypatch.setattr(worker, "DISPATCHER_TASK_TYPES", ("t1", "t2"))
    monkeypatch.setattr(worker, "settings", SimpleNamespace(WORKER_CONCURRENCY=2))

    class ActiveProcessing(set):
        def add(self, item):
            ports.active_processing_ops.append(("add", item.get_name()))
            super().add(item)

        def discard(self, item):
            ports.active_processing_ops.append(("discard", item.get_name()))
            super().discard(item)

    monkeypatch.setattr(worker, "_v2_active_processing", ActiveProcessing())
    monkeypatch.setattr(worker, "_v2_worker_draining", False)
    monkeypatch.setattr(worker, "_v2_worker_running", False)

    class Semaphore:
        async def acquire(self):
            ports.events.append("acquire")
            if ports.on_acquire is not None:
                ports.on_acquire()
            return True

        def release(self):
            ports.events.append("release")

    semaphore = Semaphore()

    from app.core import worker_concurrency

    async def get_semaphore():
        ports.events.append("semaphore-ready")
        return semaphore

    monkeypatch.setattr(worker_concurrency, "get_worker_semaphore", get_semaphore)

    async def claim(task_types, lease_sec):
        ports.claim_calls.append((task_types, lease_sec))
        if ports.claim_outcomes:
            outcome = ports.claim_outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        return None

    monkeypatch.setattr(worker, "_try_claim_any_v2", claim)

    async def process(task, lease_sec, sem_value):
        ports.processing_calls.append((task, lease_sec, sem_value))

    monkeypatch.setattr(worker, "_process_claimed_task_v2", process)

    def create_task(coro, *, name=None):
        ports.spawned_names.append(name)
        return asyncio.create_task(coro, name=name)

    async def fake_sleep(seconds):
        ports.sleeps.append(seconds)
        await asyncio.sleep(0)
        if ports.stop_on_sleep is not None and ports.stop_on_sleep(
            len(ports.sleeps), seconds
        ):
            worker._v2_worker_running = False
        if len(ports.sleeps) >= 50:
            worker._v2_worker_running = False

    monkeypatch.setattr(
        worker,
        "asyncio",
        SimpleNamespace(
            create_task=create_task,
            sleep=fake_sleep,
            CancelledError=asyncio.CancelledError,
        ),
    )
    ports.semaphore = semaphore
    return ports


def log_messages(ports, kind):
    return [entry[1][0] for entry in ports.logs if entry[0] == kind]


@pytest.mark.asyncio
async def test_dispatcher_spawns_named_processing_and_releases_slot(ports):
    claimed = value()
    ports.claim_outcomes = [claimed]
    ports.stop_on_sleep = lambda count, seconds: seconds == 6.0

    await worker.run_dispatcher_v2(poll_interval=6.0, lease_sec=7)

    assert ports.claim_calls == [(("t1", "t2"), 7), (("t1", "t2"), 7)]
    assert ports.processing_calls == [(claimed, 7, ports.semaphore)]
    assert ports.spawned_names == ["proc:task-1"]
    assert ports.events == ["semaphore-ready", "acquire", "acquire", "release"]
    assert ports.sleeps == [0, 6.0]
    assert worker._v2_active_processing == set()
    assert ports.active_processing_ops == [
        ("add", "proc:task-1"),
        ("discard", "proc:task-1"),
    ]
    assert worker._v2_worker_running is False
    assert "v2 Dispatcher stopped" in log_messages(ports, "info")
    start = next(
        args
        for kind, args in ports.logs
        if kind == "info" and args[0].startswith("v2 Dispatcher started")
    )
    assert start == (
        "v2 Dispatcher started: concurrency=%d poll=%ss",
        2,
        6.0,
    )


@pytest.mark.asyncio
async def test_dispatcher_releases_slot_and_stops_when_draining(ports):
    def start_draining():
        worker._v2_worker_draining = True

    ports.on_acquire = start_draining

    await worker.run_dispatcher_v2(poll_interval=6.0, lease_sec=7)

    assert ports.claim_calls == []
    assert ports.events == ["semaphore-ready", "acquire", "release"]
    assert worker._v2_worker_running is False
    assert "v2 Dispatcher stopped" in log_messages(ports, "info")


@pytest.mark.asyncio
async def test_dispatcher_redis_failure_counts_and_backs_off(ports):
    error = TaskQueueUnavailableError("redis-down", retry_after=10)
    ports.claim_outcomes = [error]
    ports.stop_on_sleep = lambda count, seconds: seconds == 10

    await worker.run_dispatcher_v2(poll_interval=6.0, lease_sec=7)

    assert ports.metrics == {"queue_redis_failure": 1}
    assert ports.sleeps == [10]
    assert ports.events == ["semaphore-ready", "acquire", "release"]
    failed = next(args for kind, args in ports.logs if kind == "error")
    assert failed == (
        "v2 Dispatcher Redis unavailable (failure #%d): %s — backing off %ds",
        1,
        error,
        10,
    )
    assert log_messages(ports, "critical") == []


@pytest.mark.asyncio
async def test_dispatcher_circuit_breaker_probes_in_five_second_steps(ports):
    ports.claim_outcomes = [TaskQueueUnavailableError("redis-down", retry_after=1)] * 10
    ports.stop_on_sleep = lambda count, seconds: count == 16

    await worker.run_dispatcher_v2(poll_interval=6.0, lease_sec=7)

    assert ports.metrics == {"queue_redis_failure": 10}
    assert ports.sleeps[:9] == [1, 2, 4, 8, 16, 16, 16, 16, 16]
    assert ports.sleeps[9:] == [5, 5, 5, 5, 5, 5, 2]
    critical = next(args for kind, args in ports.logs if kind == "critical")
    assert critical == (
        "v2 Dispatcher circuit breaker OPEN after %d Redis failures — "
        "entering degraded probe mode (worker stays alive, retries periodically)",
        10,
    )


@pytest.mark.asyncio
async def test_dispatcher_probe_stops_early_when_draining(ports):
    ports.claim_outcomes = [TaskQueueUnavailableError("redis-down", retry_after=1)] * 10

    def stop_policy(count, seconds):
        if count == 10:
            worker._v2_worker_draining = True
        if count == 12:
            worker._v2_worker_running = False
        return False

    ports.stop_on_sleep = stop_policy

    await worker.run_dispatcher_v2(poll_interval=6.0, lease_sec=7)

    assert ports.sleeps == [1, 2, 4, 8, 16, 16, 16, 16, 16, 5]
    assert ports.metrics == {"queue_redis_failure": 10}


@pytest.mark.asyncio
async def test_dispatcher_probe_stops_early_when_stopping(ports):
    ports.claim_outcomes = [TaskQueueUnavailableError("redis-down", retry_after=1)] * 10

    def stop_policy(count, seconds):
        if count == 10:
            worker._v2_worker_running = False
        return False

    ports.stop_on_sleep = stop_policy

    await worker.run_dispatcher_v2(poll_interval=6.0, lease_sec=7)

    assert ports.sleeps == [1, 2, 4, 8, 16, 16, 16, 16, 16, 5]
    assert ports.metrics == {"queue_redis_failure": 10}


@pytest.mark.asyncio
async def test_dispatcher_backoff_is_capped_at_three_hundred(ports):
    error = TaskQueueUnavailableError("redis-down", retry_after=1000)
    ports.claim_outcomes = [error]
    ports.stop_on_sleep = lambda count, seconds: seconds == 300

    await worker.run_dispatcher_v2(poll_interval=6.0, lease_sec=7)

    assert ports.sleeps == [300]
    failed = next(args for kind, args in ports.logs if kind == "error")
    assert failed[1] == 1 and failed[3] == 300


@pytest.mark.asyncio
async def test_dispatcher_successful_claim_resets_failure_count(ports):
    ports.claim_outcomes = [
        TaskQueueUnavailableError("redis-down", retry_after=1),
        None,
        TaskQueueUnavailableError("redis-down", retry_after=1),
    ]
    ports.stop_on_sleep = lambda count, seconds: count == 3

    await worker.run_dispatcher_v2(poll_interval=5.0, lease_sec=7)

    assert ports.sleeps == [1, 5.0, 1]
    failures = [args[1] for kind, args in ports.logs if kind == "error"]
    assert failures == [1, 1]


@pytest.mark.asyncio
async def test_dispatcher_cancellation_logs_and_resets(ports):
    never = asyncio.Event()

    async def claim(task_types, lease_sec):
        ports.claim_calls.append((task_types, lease_sec))
        await never.wait()

    worker._try_claim_any_v2 = claim
    runner = asyncio.create_task(
        worker.run_dispatcher_v2(poll_interval=6.0, lease_sec=7)
    )
    for _ in range(50):
        await asyncio.sleep(0.01)
        if ports.claim_calls:
            break
    runner.cancel()

    with pytest.raises(asyncio.CancelledError):
        await runner

    assert worker._v2_worker_running is False
    assert "v2 Dispatcher cancelled" in log_messages(ports, "info")
    assert "v2 Dispatcher stopped" in log_messages(ports, "info")
