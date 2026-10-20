"""Worker startup preserves partial task publication and caller failure policy."""

import asyncio
import builtins

import pytest

from app.core.runtime_task_shutdown import cancel_and_wait_runtime_tasks
from tests.core.runtime_http_worker_ports import worker_ports as worker_ports
from tests.core.runtime_http_worker_probe import http_worker_operations

STAGES = [
    ("factory:dispatcher", "Pipeline dispatcher v2"),
    ("create:pipeline-dispatcher-v2", "Pipeline dispatcher v2"),
    ("factory:reaper", "Reaper"),
    ("create:task-reaper-v2", "Reaper"),
    ("prewarm", "AI prewarm worker"), ("log", "AI prewarm worker"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("production", [False, True])
async def test_worker_tasks_are_real_named_owned_and_feed_existing_shutdown(worker_ports, production):
    state = worker_ports
    assert state.tasks.pipeline_worker_task is state.tasks.reaper_task is None
    assert await state.operations.start(state.tasks, production, state.logger, state.report) is None
    assert [task.get_name() for task in state.created] == ["pipeline-dispatcher-v2", "task-reaper-v2"]
    assert [state.tasks.pipeline_worker_task, state.tasks.reaper_task] == state.created
    assert state.events == [
        "factory:dispatcher", "create:pipeline-dispatcher-v2",
        "factory:reaper", "create:task-reaper-v2", "prewarm", "log",
    ]
    state.report.assert_not_called()
    state.logger.info.assert_called_once_with("AI prewarm worker started")
    await asyncio.sleep(0)
    await cancel_and_wait_runtime_tasks([
        ("pipeline-dispatcher-v2", state.tasks.pipeline_worker_task),
        ("task-reaper-v2", state.tasks.reaper_task),
    ])
    assert all(task.done() and task.cancelled() for task in state.created)
    assert "end:dispatcher" in state.events and "end:reaper" in state.events


@pytest.mark.asyncio
@pytest.mark.parametrize("failed,component", STAGES)
@pytest.mark.parametrize("production", [False, True])
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_worker_partial_startup_error_preserves_handles_and_reporter_boundary(
    worker_ports, failed, component, production, error_type,
):
    state = worker_ports
    state.failed, state.error = failed, error_type("synthetic HTTP worker failure")

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
        assert "prewarm" in state.events
    if error_type is asyncio.CancelledError:
        state.report.assert_not_called()
    else:
        state.report.assert_called_once_with(component, state.error, production)
    expected_dispatcher = not failed.endswith("dispatcher") and failed != "create:pipeline-dispatcher-v2"
    expected_reaper = (
        component == "AI prewarm worker"
        or (component == "Pipeline dispatcher v2" and not production and error_type is RuntimeError)
    )
    assert (state.tasks.pipeline_worker_task is not None) is expected_dispatcher
    assert (state.tasks.reaper_task is not None) is expected_reaper
    assert [task for task in [state.tasks.pipeline_worker_task, state.tasks.reaper_task] if task] == state.created
    assert all(not task.done() for task in state.created)


@pytest.mark.asyncio
@pytest.mark.parametrize("position,component", [
    ("dispatcher", "Pipeline dispatcher v2"), ("reaper", "Reaper"), ("prewarm", "AI prewarm worker"),
])
@pytest.mark.parametrize("error_type", [ImportError, asyncio.CancelledError])
async def test_worker_import_failure_has_original_independent_catch(worker_ports, monkeypatch, position, component, error_type):
    state = worker_ports
    importing = builtins.__import__
    error = error_type("synthetic worker import failure")
    queue_imports = 0

    def controlled(name, *args, **kwargs):
        nonlocal queue_imports
        if name == "app.services.task_queue_worker":
            queue_imports += 1
            if queue_imports == (1 if position == "dispatcher" else 2 if position == "reaper" else -1):
                raise error
        if name == "app.services.ai_prewarm_worker" and position == "prewarm":
            raise error
        return importing(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", controlled)
    if error_type is asyncio.CancelledError:
        with pytest.raises(asyncio.CancelledError) as caught:
            await state.operations.start(state.tasks, False, state.logger, state.report)
        assert caught.value is error
        state.report.assert_not_called()
    else:
        await state.operations.start(state.tasks, False, state.logger, state.report)
        state.report.assert_called_once_with(component, error, False)
    assert all(not task.done() for task in state.created)


def test_worker_task_states_are_independent_and_have_no_task_management_methods():
    state_type = http_worker_operations().state
    first, second = state_type(), state_type()
    first.pipeline_worker_task = object()
    assert first is not second and second.pipeline_worker_task is second.reaper_task is None
    assert not any(hasattr(first, method) for method in ["create", "cancel", "wait_all", "register"])
