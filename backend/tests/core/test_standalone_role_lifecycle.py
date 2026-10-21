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
async def test_initialization_failure_after_registry_cleans_role_and_preserves_error(
    role_runtime, role, error_type, stage,
):
    state = role_runtime
    state.cloud = True
    failed = {
        "config.async": "config.async",
        "role.init": "prewarm.start" if role == "worker" else "audit.start",
        "signals.install": "signals.install",
    }[stage]
    error = error_type("synthetic full role startup error")
    state.failures[failed] = error
    if stage == "config.async":
        expected = error_type
    elif error_type is asyncio.CancelledError:
        expected = asyncio.CancelledError
    elif role == "worker":
        expected = SystemError
    else:
        expected = SystemError
    with pytest.raises(expected) as caught:
        await bootstrap._run_role_async(role)
    assert (caught.value.__cause__ if expected is SystemError else caught.value) is error
    if stage == "config.async":
        assert not state.registries
        assert not [event for event in state.events if event in COMMON_STOP]
    else:
        assert len(state.registries) == 1
        assert all(item._task.done() for item in state.registries[0]._tasks)
        assert [event for event in state.events if event in COMMON_STOP] == COMMON_STOP


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["worker", "scheduler"])
async def test_signal_wait_cancellation_cleans_role_and_propagates(role_runtime, role):
    state = role_runtime
    state.auto_stop = False
    runner = asyncio.create_task(bootstrap._run_role_async(role))
    try:
        await asyncio.wait_for(state.signal_ready.wait(), timeout=5)
        runner.cancel()
        with pytest.raises(asyncio.CancelledError):
            await runner
        assert [event for event in state.events if event in COMMON_STOP] == COMMON_STOP
        assert all(item._task.done() for item in state.registries[0]._tasks)
    finally:
        if not runner.done():
            runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_role_cleanup_error_does_not_override_post_startup_error(
    role_runtime, error_type,
):
    state = role_runtime
    startup_error = error_type("synthetic role startup error")
    state.failures["prewarm.start"] = startup_error
    state.failures["pdf.stop"] = RuntimeError("synthetic cleanup failure")
    expected = error_type if error_type is asyncio.CancelledError else SystemError
    with pytest.raises(expected) as caught:
        await bootstrap._run_role_async("worker")
    assert (
        caught.value.__cause__ if expected is SystemError else caught.value
    ) is startup_error
    assert [event for event in state.events if event in COMMON_STOP] == COMMON_STOP
    assert state.logger.warning.called


@pytest.mark.asyncio
async def test_original_system_error_is_rethrown_without_rewrapping(role_runtime):
    state = role_runtime
    error = SystemError("synthetic original system error")
    state.failures["prewarm.start"] = error

    with pytest.raises(SystemError) as caught:
        await bootstrap._run_role_async("worker")

    assert caught.value is error
    assert [event for event in state.events if event in COMMON_STOP] == COMMON_STOP


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
async def test_worker_partial_ocr_failure_runs_reachable_role_cleanup_and_keeps_error(
    role_runtime, failed, error_type,
):
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
    expected = [event for event in COMMON_STOP if event != "ocr.executor.stop"]
    assert [event for event in state.events if event in COMMON_STOP] == expected
    assert ("ocr.gateway.stop" in state.events) is (failed == "ocr.gateway.publish")
    assert ("ocr.worker.stop" in state.events) is (failed == "ocr.gateway.create")
    assert "ocr.gateway.global" not in state.events
    assert len(state.registries) == 1 and not state.registries[0]._tasks


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_worker_client_cleanup_failure_does_not_replace_gateway_startup_error(
    role_runtime, error_type,
):
    state = role_runtime
    state.cloud, state.ocr_enabled = True, True
    startup_error = error_type("synthetic gateway construction failure")
    state.failures["ocr.gateway.create"] = startup_error
    state.failures["ocr.worker.stop"] = RuntimeError("synthetic worker close failure")
    expected = asyncio.CancelledError if error_type is asyncio.CancelledError else SystemError
    with pytest.raises(expected) as caught:
        await bootstrap._run_role_async("worker")
    assert (
        caught.value.__cause__ if expected is SystemError else caught.value
    ) is startup_error
    assert "ocr.worker.stop" in state.events
    assert "ocr.gateway.global" not in state.events


@pytest.mark.asyncio
@pytest.mark.parametrize("startup", ["error", "cancel"])
@pytest.mark.parametrize("cleanup", ["error", "cancel"])
async def test_startup_error_survives_cleanup_failure_and_cancellation(
    role_runtime, startup, cleanup,
):
    state = role_runtime
    state.cloud, state.ocr_enabled = True, True
    startup_error = {
        "error": RuntimeError("synthetic startup failure"),
        "cancel": asyncio.CancelledError("synthetic startup cancellation"),
    }[startup]
    cleanup_error = {
        "error": RuntimeError("synthetic cleanup failure"),
        "cancel": asyncio.CancelledError("synthetic cleanup cancellation"),
    }[cleanup]
    state.failures.update({
        "ocr.gateway.create": startup_error,
        "ocr.worker.stop": cleanup_error,
    })
    expected = asyncio.CancelledError if startup == "cancel" else SystemError
    with pytest.raises(expected) as caught:
        await bootstrap._run_role_async("worker")
    if startup == "cancel":
        assert caught.value is startup_error
    else:
        assert caught.value.__cause__ is startup_error
    assert state.events.count("ocr.worker.stop") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_startup_cancellation_is_not_replaced_by_cleanup_error(
    role_runtime, error_type,
):
    state = role_runtime
    state.cloud, state.ocr_enabled = True, True
    startup_error = error_type("synthetic startup cancellation")
    logger_error = RuntimeError("synthetic startup logger failure")
    state.logger.critical.side_effect = logger_error
    state.failures["ocr.gateway.create"] = startup_error
    expected = asyncio.CancelledError if error_type is asyncio.CancelledError else SystemError
    with pytest.raises(expected) as caught:
        await bootstrap._run_role_async("worker")
    if error_type is asyncio.CancelledError:
        assert caught.value is startup_error
    else:
        assert caught.value.__cause__ is startup_error


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["worker", "scheduler"])
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_staging_startup_failure_precedes_registry_and_preserves_nonfatal_boundary(role_runtime, role, error_type):
    state = role_runtime
    error = error_type("synthetic complete startup sweep failure")
    state.failures["staging.sweep"] = error
    if error_type is asyncio.CancelledError:
        with pytest.raises(asyncio.CancelledError) as caught:
            await bootstrap._run_role_async(role)
        assert caught.value is error
        assert state.events == ["logging.setup", "config.sync", "config.async", "staging.sweep"]
        assert not state.registries
    else:
        await bootstrap._run_role_async(role)
        state.logger.warning.assert_any_call(
            "Staging temp sweep failed (non-fatal)", exc_info=True,
        )
        assert len(state.registries) == 1
        assert all(item._task.done() for item in state.registries[0]._tasks)
        assert [event for event in state.events if event in COMMON_STOP] == COMMON_STOP
