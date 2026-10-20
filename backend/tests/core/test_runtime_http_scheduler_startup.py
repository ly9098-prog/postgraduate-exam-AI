"""Scheduler startup preserves partial tasks and three failure policies."""

import asyncio
import builtins

import pytest

from app.core.runtime_task_shutdown import cancel_and_wait_runtime_tasks
from tests.core.runtime_http_scheduler_ports import scheduler_ports as scheduler_ports
from tests.core.runtime_http_scheduler_probe import http_scheduler_operations

TASK_NAMES = [
    "scheduler-heartbeat", "token-cleanup", "staging-cleanup",
    "export-processor", "export-cleanup", "outbox-dispatcher", "outbox-reconciler",
]
TASK_FIELDS = [
    "scheduler_heartbeat_task", "cleanup_task", "staging_cleanup_task",
    "export_processor_task", "export_cleanup_task",
    "outbox_dispatcher_task", "outbox_reconciler_task",
]
FATAL_COMPONENTS = [
    ("create:scheduler-heartbeat", "Scheduler heartbeat"),
    ("audit.start", "Audit log cleanup scheduler"),
    ("metrics.start", "Recommendation metrics scheduler"),
]
BARE_TASKS = ["token-cleanup", "staging-cleanup", "export-processor", "export-cleanup"]


@pytest.mark.asyncio
@pytest.mark.parametrize("production", [False, True])
async def test_scheduler_tasks_are_real_named_owned_and_feed_existing_shutdown(scheduler_ports, production):
    state = scheduler_ports
    assert all(getattr(state.tasks, field) is None for field in TASK_FIELDS)
    assert await state.operations.start(state.tasks, production, state.logger, state.report) is None
    assert [task.get_name() for task in state.created] == TASK_NAMES
    assert [
        state.tasks.scheduler_heartbeat_task, state.tasks.cleanup_task,
        state.tasks.staging_cleanup_task, state.tasks.export_processor_task,
        state.tasks.export_cleanup_task, state.tasks.outbox_dispatcher_task,
        state.tasks.outbox_reconciler_task,
    ] == state.created
    assert state.events[:3] == ["factory:heartbeat", "create:scheduler-heartbeat", "audit.start"]
    assert state.events.index("metrics.start") < state.events.index("factory:token")
    assert "log" in state.events and "warn" not in state.events
    state.report.assert_not_called()
    await asyncio.sleep(0)
    await cancel_and_wait_runtime_tasks([
        (name, getattr(state.tasks, field))
        for name, field in zip(TASK_NAMES, TASK_FIELDS, strict=True)
    ])
    assert all(task.done() and task.cancelled() for task in state.created)


@pytest.mark.asyncio
@pytest.mark.parametrize("failed,component", FATAL_COMPONENTS)
@pytest.mark.parametrize("production", [False, True])
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_scheduler_fatal_failure_keeps_partial_tasks_and_reporter_boundary(
    scheduler_ports, failed, component, production, error_type,
):
    state = scheduler_ports
    state.failed, state.error = failed, error_type("synthetic HTTP scheduler failure")

    def report(_component, error, fatal):
        if fatal:
            raise SystemError("synthetic caller fatal policy") from error

    state.report.side_effect = report
    if production or error_type is asyncio.CancelledError:
        wrapped = production and error_type is RuntimeError
        with pytest.raises(SystemError if wrapped else error_type) as caught:
            await state.operations.start(state.tasks, production, state.logger, state.report)
        assert (caught.value.__cause__ if wrapped else caught.value) is state.error
        assert state.events[-1] == failed
    else:
        assert await state.operations.start(state.tasks, production, state.logger, state.report) is None
        assert "create:token-cleanup" in state.events
    if error_type is asyncio.CancelledError:
        state.report.assert_not_called()
    else:
        state.report.assert_called_once_with(component, state.error, production)
    if production or error_type is asyncio.CancelledError:
        expected = [name for name in TASK_NAMES if f"create:{name}" in state.events and state.events.index(f"create:{name}") < state.events.index(failed)]
    else:
        # Non-fatal RuntimeError: the function continues after the report, so
        # all tasks except the failed one are created.
        expected = [name for name in TASK_NAMES if f"create:{name}" in state.events and name != failed.replace("create:", "")]
    actual = [task.get_name() for task in state.created]
    assert actual == expected
    assert all(not task.done() for task in state.created)


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", BARE_TASKS)
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_scheduler_bare_task_failure_propagates_without_catch_or_report(scheduler_ports, failed, error_type):
    state = scheduler_ports
    state.failed, state.error = f"create:{failed}", error_type("synthetic bare task failure")
    with pytest.raises(error_type) as caught:
        await state.operations.start(state.tasks, False, state.logger, state.report)
    assert caught.value is state.error
    state.report.assert_not_called()
    assert "warn" not in state.events
    created = [task.get_name() for task in state.created]
    assert failed not in created
    assert all(name in created for name in TASK_NAMES[:TASK_NAMES.index(failed)])
    assert all(not task.done() for task in state.created)


@pytest.mark.asyncio
async def test_scheduler_outbox_failure_preserves_warning_boundary_and_remaining_tasks(scheduler_ports):
    state = scheduler_ports
    state.failed, state.error = "factory:outbox_dispatcher", RuntimeError("synthetic outbox failure")
    assert await state.operations.start(state.tasks, False, state.logger, state.report) is None
    state.report.assert_not_called()
    assert "warn" in state.events
    created = [task.get_name() for task in state.created]
    assert "outbox-dispatcher" not in created and "outbox-reconciler" not in created
    assert all(name in created for name in TASK_NAMES[:5])
    assert all(not task.done() for task in state.created)


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [ImportError, asyncio.CancelledError])
async def test_scheduler_outbox_import_failure_keeps_warning_boundary(scheduler_ports, monkeypatch, error_type):
    state = scheduler_ports
    error = error_type("synthetic outbox import failure")
    importing = builtins.__import__

    def controlled(name, *args, **kwargs):
        if name == "app.services.outbox_service":
            raise error
        return importing(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", controlled)
    if error_type is asyncio.CancelledError:
        with pytest.raises(asyncio.CancelledError) as caught:
            await state.operations.start(state.tasks, False, state.logger, state.report)
        assert caught.value is error
        state.report.assert_not_called()
        assert "warn" not in state.events
    else:
        assert await state.operations.start(state.tasks, False, state.logger, state.report) is None
        assert "warn" in state.events
    assert "outbox-dispatcher" not in [task.get_name() for task in state.created]


def test_scheduler_task_states_are_independent_and_have_no_task_management_methods():
    state_type = http_scheduler_operations().state
    first, second = state_type(), state_type()
    first.cleanup_task = object()
    assert first is not second and second.cleanup_task is None
    assert not any(hasattr(first, method) for method in ["create", "cancel", "wait_all", "register"])
