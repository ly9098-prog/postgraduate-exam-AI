"""Run real standalone startup, signal waiting and ordered shutdown."""

import asyncio

import pytest

from app.core import bootstrap
from tests.core.standalone_role_ports import role_runtime as role_runtime

COMMON_STOP = ["formula.stop", "executors.stop", "executors.clear", "pdf.stop", "queue.close", "db.dispose", "orphans.stop"]
WORKER_TASKS = ["pipeline-dispatcher-v2", "task-reaper-v2"]
SCHEDULER_TASKS = [
    "scheduler-heartbeat", "token-cleanup", "staging-cleanup", "export-processor",
    "export-cleanup", "outbox-dispatcher", "outbox-reconciler",
    "answer-projection-reconciler", "async-task-health-monitor",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["worker", "scheduler"])
@pytest.mark.parametrize("cloud", [False, True])
@pytest.mark.parametrize("ocr_enabled", [False, True])
async def test_full_role_lifecycle_owns_real_tasks_and_original_resource_order(role_runtime, role, cloud, ocr_enabled):
    state = role_runtime
    state.cloud, state.ocr_enabled = cloud, ocr_enabled
    await bootstrap._run_role_async(role)
    events = state.events
    assert events[:4] == ["logging.setup", "config.sync", "config.async", "staging.sweep"]
    assert len(state.registries) == 1
    tasks = state.registries[0]._tasks
    assert [item.name for item in tasks] == (WORKER_TASKS if role == "worker" else SCHEDULER_TASKS)
    assert all(item._task.done() for item in tasks)
    assert [event for event in events if event in COMMON_STOP] == COMMON_STOP
    assert events.index("signals.install") < events.index("formula.stop")
    if role == "worker":
        assert events.index("queue.drain") < events.index("reaper.signal") < events.index("prewarm.stop") < events.index("formula.stop")
        assert ("ocr.executor.stop" in events) is (not cloud)
        assert ("ocr.gateway.stop" in events) is ocr_enabled
        assert events.index("orphans.start") < events.index("prewarm.start")
        assert "audit.start" not in events
    else:
        assert events.index("queue.draining") < events.index("audit.stop") < events.index("metrics.stop") < events.index("export.signal") < events.index("formula.stop")
        assert not any(event.startswith("ocr.") for event in events)
        assert state.enqueue is not None
        assert await state.enqueue("synthetic-id", "synthetic-kind", {}, 2) == "synthetic-task"
    assert all(events.index(event) < events.index("formula.stop") for event in events if event.startswith("end:"))


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["worker", "scheduler"])
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
@pytest.mark.parametrize("stage", ["config.async", "role.init", "signals.install"])
async def test_existing_initialization_failure_does_not_run_shutdown_finally(role_runtime, role, error_type, stage):
    state = role_runtime
    state.cloud = True
    failed = ("prewarm.start" if role == "worker" else "metrics.start") if stage == "role.init" else stage
    error = error_type("synthetic full role startup error")
    state.failures[failed] = error
    wrapped = stage == "role.init" and error_type is RuntimeError
    with pytest.raises(SystemError if wrapped else error_type) as caught:
        await bootstrap._run_role_async(role)
    assert (caught.value.__cause__ if wrapped else caught.value) is error
    assert not [event for event in state.events if event in COMMON_STOP]
    if stage == "config.async":
        assert not state.registries
    else:
        assert len(state.registries) == 1
        assert all(not item._task.done() for item in state.registries[0]._tasks)
    # Fixture cleanup is separate from the production path's missing finally.


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["worker", "scheduler"])
async def test_current_signal_wait_task_cancellation_does_not_enter_shutdown(role_runtime, role):
    state = role_runtime
    state.auto_stop = False
    runner = asyncio.create_task(bootstrap._run_role_async(role))
    try:
        await asyncio.wait_for(state.signal_ready.wait(), timeout=5)
        runner.cancel()
        with pytest.raises(asyncio.CancelledError):
            await runner
        assert not [event for event in state.events if event in COMMON_STOP]
        assert all(not item._task.done() for item in state.registries[0]._tasks)
    finally:
        if not runner.done():
            runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", ["executors.stop", "pdf.stop", "queue.close", "db.dispose", "orphans.stop"])
async def test_resource_error_preserves_remaining_standalone_shutdown(role_runtime, failed):
    state = role_runtime
    state.failures[failed] = RuntimeError("synthetic close failure")
    await bootstrap._run_role_async("worker")
    skipped = {"executors.clear"} if failed == "executors.stop" else set()
    assert [event for event in state.events if event in COMMON_STOP] == [name for name in COMMON_STOP if name not in skipped]
    assert all(item._task.done() for item in state.registries[0]._tasks)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["worker", "scheduler"])
@pytest.mark.parametrize("failed", ["pdf.stop", "db.dispose"])
async def test_shutdown_cancellation_propagates_and_skips_later_resources(role_runtime, role, failed):
    state = role_runtime
    error = asyncio.CancelledError("synthetic resource shutdown cancellation")
    state.failures[failed] = error
    with pytest.raises(asyncio.CancelledError) as caught:
        await bootstrap._run_role_async(role)
    assert caught.value is error
    assert [event for event in state.events if event in COMMON_STOP] == COMMON_STOP[:COMMON_STOP.index(failed) + 1]
    assert all(item._task.done() for item in state.registries[0]._tasks)
    assert "orphans.stop" not in state.events


@pytest.mark.asyncio
async def test_unknown_standalone_role_is_rejected_after_common_checks(role_runtime):
    state = role_runtime
    with pytest.raises(SystemError, match="Unknown standalone role") as caught:
        await bootstrap._run_role_async("synthetic-invalid-role")
    assert isinstance(caught.value.__cause__, ValueError)
    assert state.events == ["logging.setup", "config.sync", "config.async", "staging.sweep"]
    assert len(state.registries) == 1 and not state.registries[0]._tasks


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", ["ocr.worker.create", "ocr.gateway.create", "ocr.gateway.publish"])
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_worker_partial_ocr_failure_keeps_runner_error_and_no_shutdown_boundary(role_runtime, failed, error_type):
    state = role_runtime
    state.cloud, state.ocr_enabled = True, True
    error = error_type("synthetic partial worker OCR startup failure")
    state.failures[failed] = error
    wrapped = error_type is RuntimeError
    with pytest.raises(SystemError if wrapped else error_type) as caught:
        await bootstrap._run_role_async("worker")
    assert (caught.value.__cause__ if wrapped else caught.value) is error
    assert ("ocr.gateway.publish" in state.events) is (failed == "ocr.gateway.publish")
    assert (state.gateway is not None) is (failed == "ocr.gateway.publish")
    assert "orphans.start" not in state.events and "signals.install" not in state.events
    assert not [event for event in state.events if event in COMMON_STOP]
    assert len(state.registries) == 1 and not state.registries[0]._tasks
