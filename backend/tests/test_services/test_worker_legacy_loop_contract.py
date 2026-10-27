"""Contracts for the legacy v1 pipeline worker loop supervision."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.services import task_queue_worker as worker


class Ports:
    def __init__(self):
        self.events = []
        self.logs = []
        self.metrics = {"owner_fencing_rejected": 0}
        self.sleeps = []
        self.dequeue_calls = []
        self.dequeue_outcomes = []
        self.complete_calls = []
        self.fail_calls = []
        self.complete_result = True
        self.fail_result = True
        self.owner_lost = None
        self.heartbeat_leases = []


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
            exception=record("exception"),
        ),
    )
    monkeypatch.setattr(worker, "queue_metrics", ports.metrics)
    monkeypatch.setattr(worker, "DISPATCHER_TASK_TYPES", ("t1",))

    class Queue:
        async def dequeue(self, task_type, lease_sec=0):
            ports.dequeue_calls.append((task_type, lease_sec))
            if ports.dequeue_outcomes:
                outcome = ports.dequeue_outcomes.pop(0)
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome
            return None

        async def complete(self, task):
            ports.complete_calls.append(task)
            return ports.complete_result

        async def fail(self, task, error):
            ports.fail_calls.append((task, error))
            return ports.fail_result

    monkeypatch.setattr(worker, "task_queue", Queue())

    async def fake_sleep(seconds):
        ports.sleeps.append(seconds)
        worker._worker_running = False

    monkeypatch.setattr(
        worker,
        "asyncio",
        SimpleNamespace(
            Event=asyncio.Event,
            create_task=asyncio.create_task,
            CancelledError=asyncio.CancelledError,
            sleep=fake_sleep,
        ),
    )
    return ports


def task(task_id="task-1", task_type="t1"):
    return SimpleNamespace(task_id=task_id, task_type=task_type)


def install_supervision(ports, monkeypatch, process, *, monitor=None):
    never = asyncio.Event()

    async def heartbeat(task_value, lease_sec, owner_lost):
        ports.events.append("heartbeat-start")
        ports.owner_lost = owner_lost
        ports.heartbeat_leases.append(lease_sec)
        try:
            await never.wait()
        finally:
            ports.events.append("heartbeat-finally")

    async def default_monitor(processing_task, owner_lost):
        ports.events.append("monitor-start")
        try:
            await never.wait()
        finally:
            ports.events.append("monitor-finally")

    monkeypatch.setattr(worker, "_heartbeat_loop", heartbeat)
    monkeypatch.setattr(worker, "_cancel_on_owner_loss", monitor or default_monitor)
    monkeypatch.setattr(worker, "_process_task", process)
    return never


def log_messages(ports, kind):
    return [entry[1][0] for entry in ports.logs if entry[0] == kind]


@pytest.mark.asyncio
async def test_success_path_supervises_then_completes(ports, monkeypatch):
    async def process(value):
        ports.events.append("process-start")
        worker._worker_running = False

    install_supervision(ports, monkeypatch, process)
    ports.dequeue_outcomes = [task()]

    await worker.run_pipeline_worker(poll_interval=2.5, lease_sec=7)

    assert ports.events == [
        "heartbeat-start",
        "process-start",
        "monitor-start",
        "monitor-finally",
        "heartbeat-finally",
    ]
    assert ports.dequeue_calls == [("t1", 7)]
    assert ports.heartbeat_leases == [7]
    assert [value.task_id for value in ports.complete_calls] == ["task-1"]
    assert ports.fail_calls == []
    assert "Task completed successfully: task_id=%s" in log_messages(ports, "info")
    assert ports.metrics == {"owner_fencing_rejected": 0}


@pytest.mark.asyncio
async def test_processing_cancellation_counts_twice_and_skips_settlement(
    ports, monkeypatch
):
    never = asyncio.Event()

    async def process(value):
        ports.events.append("process-start")
        await never.wait()

    async def monitor(processing_task, owner_lost):
        owner_lost.set()
        processing_task.cancel()

    install_supervision(ports, monkeypatch, process, monitor=monitor)
    ports.dequeue_outcomes = [task(), None]

    await worker.run_pipeline_worker(poll_interval=1.0, lease_sec=5)

    assert ports.complete_calls == []
    assert ports.fail_calls == []
    assert ports.metrics == {"owner_fencing_rejected": 2}
    assert "Processing cancelled (owner lost): task_id=%s" in log_messages(
        ports, "warning"
    )
    assert "Owner lost, skipping complete/fail: task_id=%s" in log_messages(
        ports, "warning"
    )


@pytest.mark.asyncio
async def test_owner_lost_without_cancellation_skips_without_counting(
    ports, monkeypatch
):
    async def process(value):
        ports.owner_lost.set()
        worker._worker_running = False

    install_supervision(ports, monkeypatch, process)
    ports.dequeue_outcomes = [task()]

    await worker.run_pipeline_worker(poll_interval=1.0, lease_sec=5)

    assert ports.complete_calls == []
    assert ports.fail_calls == []
    assert ports.metrics == {"owner_fencing_rejected": 0}
    assert "Owner lost, skipping complete/fail: task_id=%s" in log_messages(
        ports, "warning"
    )


@pytest.mark.asyncio
async def test_complete_rejection_counts_owner_fencing(ports, monkeypatch):
    async def process(value):
        worker._worker_running = False

    install_supervision(ports, monkeypatch, process)
    ports.complete_result = False
    ports.dequeue_outcomes = [task()]

    await worker.run_pipeline_worker(poll_interval=1.0, lease_sec=5)

    assert ports.metrics == {"owner_fencing_rejected": 1}
    assert "Complete rejected (owner mismatch, fencing): task_id=%s" in log_messages(
        ports, "warning"
    )


@pytest.mark.asyncio
async def test_processing_exception_routes_to_fail(ports, monkeypatch):
    async def process(value):
        worker._worker_running = False
        raise RuntimeError("boom")

    install_supervision(ports, monkeypatch, process)
    ports.dequeue_outcomes = [task()]

    await worker.run_pipeline_worker(poll_interval=1.0, lease_sec=5)

    assert len(ports.fail_calls) == 1
    assert ports.fail_calls[0][0].task_id == "task-1"
    assert ports.fail_calls[0][1] == "boom"
    assert ports.complete_calls == []
    assert ports.metrics == {"owner_fencing_rejected": 0}
    assert "Task failed: task_id=%s type=%s" in log_messages(ports, "exception")


@pytest.mark.asyncio
async def test_fail_rejection_counts_owner_fencing(ports, monkeypatch):
    async def process(value):
        worker._worker_running = False
        raise RuntimeError("boom")

    install_supervision(ports, monkeypatch, process)
    ports.fail_result = False
    ports.dequeue_outcomes = [task()]

    await worker.run_pipeline_worker(poll_interval=1.0, lease_sec=5)

    assert ports.metrics == {"owner_fencing_rejected": 1}
    assert "Fail rejected (owner mismatch, fencing): task_id=%s" in log_messages(
        ports, "warning"
    )


@pytest.mark.asyncio
async def test_processing_exception_after_owner_loss_skips_fail(ports, monkeypatch):
    async def process(value):
        ports.owner_lost.set()
        worker._worker_running = False
        raise RuntimeError("boom")

    install_supervision(ports, monkeypatch, process)
    ports.dequeue_outcomes = [task()]

    await worker.run_pipeline_worker(poll_interval=1.0, lease_sec=5)

    assert ports.fail_calls == []
    assert ports.metrics == {"owner_fencing_rejected": 1}
    assert "Owner lost during processing, skipping fail: task_id=%s" in log_messages(
        ports, "warning"
    )


@pytest.mark.asyncio
async def test_complete_exception_routes_to_fail(ports, monkeypatch):
    async def process(value):
        worker._worker_running = False

    class RaisingQueue:
        async def dequeue(self, task_type, lease_sec=0):
            ports.dequeue_calls.append((task_type, lease_sec))
            return ports.dequeue_outcomes.pop(0) if ports.dequeue_outcomes else None

        async def complete(self, task):
            ports.complete_calls.append(task)
            raise RuntimeError("complete-down")

        async def fail(self, task, error):
            ports.fail_calls.append((task, error))
            return ports.fail_result

    install_supervision(ports, monkeypatch, process)
    monkeypatch.setattr(worker, "task_queue", RaisingQueue())
    ports.dequeue_outcomes = [task()]

    await worker.run_pipeline_worker(poll_interval=1.0, lease_sec=5)

    assert ports.fail_calls[0][1] == "complete-down"
    assert "Task failed: task_id=%s type=%s" in log_messages(ports, "exception")


@pytest.mark.asyncio
async def test_dequeue_failure_warns_and_sleeps_poll_interval(ports, monkeypatch):
    ports.dequeue_outcomes = [ValueError("redis-down")]

    await worker.run_pipeline_worker()

    assert ports.sleeps == [5.0]
    assert ports.dequeue_calls == [("t1", worker._LEASE_SEC)]
    warning = next(entry for entry in ports.logs if entry[0] == "warning")
    assert warning[1][0] == "Dequeue failed for %s: %s"
    assert warning[1][1] == "t1"
    assert str(warning[1][2]) == "redis-down"


@pytest.mark.asyncio
async def test_draining_skips_dequeue_and_sleeps_one_second(ports, monkeypatch):
    monkeypatch.setattr(worker, "_worker_draining", True)

    await worker.run_pipeline_worker(poll_interval=3.0)

    assert ports.dequeue_calls == []
    assert ports.sleeps == [1, 3.0]
    assert "Worker draining — skipping dequeue" in log_messages(ports, "info")


@pytest.mark.asyncio
async def test_no_task_sleeps_poll_interval(ports, monkeypatch):
    await worker.run_pipeline_worker(poll_interval=4.0)

    assert ports.sleeps == [4.0]
    assert ports.complete_calls == []
    assert ports.fail_calls == []


@pytest.mark.asyncio
async def test_cancellation_while_idle_propagates_and_resets(ports, monkeypatch):
    never = asyncio.Event()
    dequeued = asyncio.Event()

    class BlockingQueue:
        async def dequeue(self, task_type, lease_sec=0):
            ports.dequeue_calls.append((task_type, lease_sec))
            dequeued.set()
            await never.wait()

        async def complete(self, task):
            raise AssertionError("must not complete")

        async def fail(self, task, error):
            raise AssertionError("must not fail")

    monkeypatch.setattr(worker, "task_queue", BlockingQueue())
    runner = asyncio.create_task(worker.run_pipeline_worker(poll_interval=1.0))
    await asyncio.wait_for(dequeued.wait(), 2)
    runner.cancel()

    with pytest.raises(asyncio.CancelledError):
        await runner

    assert worker._worker_running is False
    assert ports.metrics == {"owner_fencing_rejected": 0}
    assert "Pipeline worker cancelled" in log_messages(ports, "info")
    assert "Pipeline worker stopped" in log_messages(ports, "info")


@pytest.mark.asyncio
async def test_cancellation_while_processing_is_swallowed_by_owner_loss(
    ports, monkeypatch
):
    never = asyncio.Event()
    started = asyncio.Event()

    async def process(value):
        started.set()
        try:
            await never.wait()
        finally:
            ports.events.append("process-finally")

    async def monitor(processing_task, owner_lost):
        owner_lost.set()
        processing_task.cancel()

    install_supervision(ports, monkeypatch, process, monitor=monitor)
    ports.dequeue_outcomes = [task(), None]
    runner = asyncio.create_task(
        worker.run_pipeline_worker(poll_interval=1.0, lease_sec=5)
    )
    await asyncio.wait_for(started.wait(), 2)
    runner.cancel()
    await asyncio.wait_for(runner, 3)

    assert worker._worker_running is False
    assert ports.metrics == {"owner_fencing_rejected": 2}
    assert ports.complete_calls == []
    assert ports.fail_calls == []
    assert "Processing cancelled (owner lost): task_id=%s" in log_messages(
        ports, "warning"
    )


@pytest.mark.asyncio
async def test_heartbeat_failure_after_cancel_only_warns(ports, monkeypatch):
    never = asyncio.Event()

    async def heartbeat(task_value, lease_sec, owner_lost):
        ports.events.append("heartbeat-start")
        try:
            await never.wait()
        except asyncio.CancelledError:
            raise RuntimeError("hb-fail") from None

    async def process(value):
        worker._worker_running = False

    async def monitor(processing_task, owner_lost):
        try:
            await never.wait()
        finally:
            ports.events.append("monitor-finally")

    monkeypatch.setattr(worker, "_heartbeat_loop", heartbeat)
    monkeypatch.setattr(worker, "_cancel_on_owner_loss", monitor)
    monkeypatch.setattr(worker, "_process_task", process)
    ports.dequeue_outcomes = [task()]

    await worker.run_pipeline_worker(poll_interval=1.0, lease_sec=5)

    warns = [
        entry
        for entry in ports.logs
        if entry[0] == "warning"
        and entry[1][0] == "Heartbeat task raised after cancel: %s"
    ]
    assert str(warns[0][1][1]) == "hb-fail"
    assert ports.complete_calls[0].task_id == "task-1"
