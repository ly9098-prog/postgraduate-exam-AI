"""Real HTTP all-role startup retains worker partial tasks and failure policy."""

import asyncio
import builtins
import sys

import pytest

from app import main
from tests.core.http_lifespan_ports import runtime as runtime

COMPONENTS = [
    ("dispatcher", "pipeline-dispatcher-v2", "Pipeline dispatcher v2"),
    ("reaper", "task-reaper-v2", "Reaper"), ("prewarm", None, "AI prewarm worker"),
]


async def run_failed_worker(state, monkeypatch, production, error, failed_task):
    monkeypatch.setattr(main.settings, "PROCESS_ROLE", "all")
    monkeypatch.setattr(main.settings, "LOCAL_ASYNC_RUNTIME_ENABLED", True)
    monkeypatch.setattr(main, "_production_mode", production)
    fatal = production or isinstance(error, asyncio.CancelledError)
    if fatal:
        wrapped = not isinstance(error, asyncio.CancelledError)
        with pytest.raises(SystemError if wrapped else type(error)) as caught:
            async with main.lifespan(main.app):
                pytest.fail("fatal worker startup must not yield")
        assert (caught.value.__cause__ if wrapped else caught.value) is error
        expected = ["event-loop-lag-monitor"]
        if failed_task != "pipeline-dispatcher-v2":
            expected.append("pipeline-dispatcher-v2")
        if failed_task is None:
            expected.append("task-reaper-v2")
        assert [task.get_name() for task in state.tasks] == expected
        assert all(not task.done() for task in state.tasks)
        assert "formula.stop" not in state.events and "db.dispose" not in state.events
        assert "audit.start" not in state.events
    else:
        async with main.lifespan(main.app):
            await asyncio.sleep(0)
        names = [task.get_name() for task in state.tasks]
        assert "scheduler-heartbeat" in names
        assert failed_task is None or failed_task not in names
        assert "db.dispose" in state.events and "formula.stop" in state.events
        assert all(task.done() for task in state.tasks)


@pytest.mark.asyncio
@pytest.mark.parametrize("label,task_name,component", COMPONENTS)
@pytest.mark.parametrize("production", [False, True])
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_worker_factory_and_prewarm_failure_keeps_real_lifespan_boundary(
    runtime, monkeypatch, label, task_name, component, production, error_type,
):
    error = error_type("synthetic complete worker factory failure")
    if label == "prewarm":
        runtime.failures["prewarm.start"] = error
    else:
        module = sys.modules["app.services.task_queue_worker"]
        name = "run_dispatcher_v2" if label == "dispatcher" else "run_reaper_loop_v2"

        def fail():
            raise error

        monkeypatch.setattr(module, name, fail)
    await run_failed_worker(runtime, monkeypatch, production, error, task_name)
    if not production and error_type is RuntimeError:
        assert "prewarm.start" in runtime.events
    if error_type is RuntimeError:
        log = runtime.logger.critical if production else runtime.logger.warning
        assert any(component in str(item) for item in log.call_args_list)


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_task", ["pipeline-dispatcher-v2", "task-reaper-v2"])
@pytest.mark.parametrize("production", [False, True])
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_worker_create_task_failure_preserves_first_published_handle(
    runtime, monkeypatch, failed_task, production, error_type,
):
    error = error_type("synthetic complete worker task creation failure")
    create = asyncio.create_task
    rejected = []

    def controlled(coroutine, **kwargs):
        if kwargs.get("name") == failed_task:
            rejected.append(coroutine)
            raise error
        return create(coroutine, **kwargs)

    monkeypatch.setattr(asyncio, "create_task", controlled)
    try:
        await run_failed_worker(runtime, monkeypatch, production, error, failed_task)
        assert len(rejected) == 1
        if not production and error_type is RuntimeError:
            assert "prewarm.start" in runtime.events
    finally:
        # The controlled factory owns this rejected coroutine; no production task owns it.
        for coroutine in rejected:
            coroutine.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("production", [False, True])
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_worker_prewarm_log_failure_keeps_original_component_report(
    runtime, monkeypatch, production, error_type,
):
    error = error_type("synthetic complete prewarm log failure")

    def info(message, *args, **kwargs):
        if message == "AI prewarm worker started":
            raise error

    runtime.logger.info.side_effect = info
    await run_failed_worker(runtime, monkeypatch, production, error, None)
    assert "prewarm.start" in runtime.events


@pytest.mark.asyncio
@pytest.mark.parametrize("label,task_name,component", COMPONENTS)
@pytest.mark.parametrize("production", [False, True])
@pytest.mark.parametrize("error_type", [ImportError, asyncio.CancelledError])
async def test_worker_lazy_import_failure_keeps_original_component_boundary(
    runtime, monkeypatch, label, task_name, component, production, error_type,
):
    error = error_type("synthetic complete worker import failure")
    importing = builtins.__import__
    queue_imports, fired = 0, False

    def controlled(name, *args, **kwargs):
        nonlocal queue_imports, fired
        if name == "app.services.task_queue_worker":
            queue_imports += 1
        target = (
            name == "app.services.task_queue_worker"
            and queue_imports == (1 if label == "dispatcher" else 2 if label == "reaper" else -1)
        ) or (name == "app.services.ai_prewarm_worker" and label == "prewarm")
        if target and not fired:
            fired = True
            raise error
        return importing(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", controlled)
    await run_failed_worker(runtime, monkeypatch, production, error, task_name)
    assert fired
    if not production and error_type is ImportError:
        assert ("prewarm.start" in runtime.events) is (label != "prewarm")
