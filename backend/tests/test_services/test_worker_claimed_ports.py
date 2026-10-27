"""Pin callback capture, live metric ports and deadline lookup timing."""

import asyncio
from unittest.mock import Mock

import pytest
import pytest_asyncio

from app.core import log_context
from app.services import task_queue_worker as worker
from app.services.db_fencing import FencingRejectedError
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
async def test_context_imports_are_bound_before_identity_generation(
    monkeypatch, harness
):
    trace = harness.trace_id

    def forbidden(*args, **kwargs):
        raise AssertionError("log callback rebound during identity generation")

    def changing(prefix):
        monkeypatch.setattr(log_context, "bind_log_context", forbidden)
        monkeypatch.setattr(log_context, "reset_log_context", forbidden)
        monkeypatch.setattr(log_context, "generate_request_id", forbidden)
        return trace(prefix)

    monkeypatch.setattr(log_context, "generate_trace_id", changing)
    await harness.run()
    assert "bind" in harness.events and "request_id" in harness.events
    assert harness.events[-2:] == ["reset", "release"]


@pytest.mark.asyncio
async def test_request_id_is_read_after_trace_generator_mutates_task(
    monkeypatch, harness
):
    task = harness.task()
    trace = harness.trace_id

    def changing(prefix):
        task.request_id = "updated-request"
        task.payload["pipeline_id"] = "updated-pipeline"
        return trace(prefix)

    monkeypatch.setattr(log_context, "generate_trace_id", changing)
    await harness.run(task)
    kwargs = harness.call("bind")[1]
    assert kwargs["pipeline_id"] == "claimed-task"
    assert kwargs["request_id"] == "updated-request"
    assert "request_id" not in harness.events


@pytest.mark.asyncio
async def test_process_and_watcher_ports_are_read_between_child_spawns(
    monkeypatch, harness
):
    spawn = harness.spawn
    calls = []

    async def process(task):
        calls.append(("process", task))

    async def watcher(process_task, event):
        calls.append(("watcher", process_task))
        await event.wait()

    def changing(coroutine, **kwargs):
        child = spawn(coroutine, **kwargs)
        if len(harness.children) == 1:
            monkeypatch.setattr(worker, "_process_task_v2", process)
        elif len(harness.children) == 2:
            monkeypatch.setattr(worker, "_cancel_on_owner_loss", watcher)
        return child

    monkeypatch.setattr(asyncio, "create_task", changing)
    await harness.run()
    assert [name for name, _ in calls] == ["process", "watcher"]
    assert calls[1][1] is harness.children[1]
    assert harness.sem.releases == 1


@pytest.mark.asyncio
async def test_complete_callback_is_read_after_business(monkeypatch, harness):
    async def complete(task):
        harness.record("new-complete", task)
        return 0

    async def process(task):
        monkeypatch.setattr(worker, "_complete_with_retry_v2", complete)

    monkeypatch.setattr(worker, "_process_task_v2", process)
    await harness.run()
    assert "new-complete" in harness.events and "complete" not in harness.events
    assert harness.metrics["owner_fencing_rejected"] == 1


@pytest.mark.asyncio
async def test_failure_metric_and_logger_are_live_after_business(monkeypatch, harness):
    metrics = {"owner_fencing_rejected": 10, "hard_deadline_exceeded": 0}
    logger = Mock()

    async def process(task):
        monkeypatch.setattr(worker, "queue_metrics", metrics)
        monkeypatch.setattr(worker, "logger", logger)
        raise FencingRejectedError("synthetic stale owner")

    monkeypatch.setattr(worker, "_process_task_v2", process)
    await harness.run()
    assert metrics["owner_fencing_rejected"] == 11
    assert harness.metrics["owner_fencing_rejected"] == 0
    assert logger.warning.called and not harness.logger.warning.called


@pytest.mark.asyncio
async def test_deadline_logging_reads_current_limit_after_task_cancellation(
    monkeypatch, harness
):
    async def process(task):
        try:
            await asyncio.Event().wait()
        finally:
            monkeypatch.setattr(worker, "_PROCESS_HARD_DEADLINE_SEC", 999)

    monkeypatch.setattr(worker, "_process_task_v2", process)
    monkeypatch.setattr(worker, "_PROCESS_HARD_DEADLINE_SEC", 0.01)
    await harness.run()
    assert harness.logger.critical.call_args.args[1] == 999
    assert harness.metrics["hard_deadline_exceeded"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_existing_heartbeat_stop_errors_remain_ignored(harness, error_type):
    harness.faults["heartbeat.stop"] = error_type("heartbeat cleanup")
    await harness.run()
    assert "complete" in harness.events
    assert harness.events[-2:] == ["reset", "release"]
    assert all(child.done() for child in harness.children)
