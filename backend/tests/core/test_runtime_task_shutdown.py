"""Characterize lifespan cancellation order and its shared grace period."""

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.core import runtime_task_shutdown

TASKS = [
    ("token-cleanup", "cleanup_task"),
    ("pipeline-dispatcher-v2", "_pipeline_worker_task"),
    ("task-reaper-v2", "_reaper_task"),
    ("staging-cleanup", "_staging_cleanup_task"),
    ("export-processor", "_export_processor_task"),
    ("export-cleanup", "_export_cleanup_task"),
    ("scheduler-heartbeat", "_scheduler_heartbeat_task"),
    ("outbox-dispatcher", "_outbox_dispatcher_task"),
    ("outbox-reconciler", "_outbox_reconciler_task"),
]


@pytest.fixture
def shutdown(monkeypatch):
    namespace = {"asyncio": asyncio, "logger": runtime_task_shutdown.logger}

    async def run(entries):
        monkeypatch.setattr(runtime_task_shutdown, "asyncio", namespace["asyncio"])
        monkeypatch.setattr(runtime_task_shutdown, "logger", namespace["logger"])
        await runtime_task_shutdown.cancel_and_wait_runtime_tasks([
            (label, task) for (label, _name), task in zip(TASKS, entries, strict=True)
        ])

    return namespace, run


class Task:
    def __init__(self, name, events, *, done=False, cancelled=False, exception=None):
        self.name = name
        self.events = events
        self.finished = done
        self.is_cancelled = cancelled
        self.failure = exception

    def done(self):
        self.events.append(("done", self.name))
        return self.finished

    def cancel(self):
        self.events.append(("cancel", self.name))

    def cancelled(self):
        return self.is_cancelled

    def exception(self):
        if isinstance(self.failure, asyncio.CancelledError):
            raise self.failure
        return self.failure


@pytest.mark.asyncio
async def test_cancel_order_ignores_missing_and_already_done_then_waits_once(shutdown):
    namespace, run = shutdown
    events = []
    entries = [Task(label, events) for label, _name in TASKS]
    entries[1] = None
    entries[4].finished = True
    waited = []

    async def wait(tasks, *, timeout):
        waited.append((list(tasks), timeout))
        return set(tasks), set()

    namespace["asyncio"] = SimpleNamespace(wait=wait, CancelledError=asyncio.CancelledError)
    await run(entries)
    selected = [task for task in entries if task is not None and not task.finished]
    assert [name for action, name in events if action == "cancel"] == [task.name for task in selected]
    assert waited == [(selected, 30)]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["cancelled", "completed", "error", "exception_cancelled", "pending"])
async def test_outcome_logging_and_pending_second_cancel(shutdown, kind):
    namespace, run = shutdown
    events = []
    failure = asyncio.CancelledError() if kind == "exception_cancelled" else RuntimeError("synthetic")
    task = Task("token-cleanup", events, cancelled=kind == "cancelled", exception=(
        failure if kind in {"error", "exception_cancelled"} else None
    ))
    log = SimpleNamespace(info=Mock(), warning=Mock())
    namespace["logger"] = log

    async def wait(tasks, *, timeout):
        assert list(tasks) == [task] and timeout == 30
        return (set(), {task}) if kind == "pending" else ({task}, set())

    namespace["asyncio"] = SimpleNamespace(wait=wait, CancelledError=asyncio.CancelledError)
    await run([task, *([None] * 8)])
    assert events.count(("cancel", "token-cleanup")) == (2 if kind == "pending" else 1)
    if kind in {"pending", "error"}:
        log.warning.assert_called_once()
        assert ("shared 30s" in log.warning.call_args.args[0]) is (kind == "pending")
    else:
        log.info.assert_called_once()
        assert ("completed" in log.info.call_args.args[0]) is (kind == "completed")


@pytest.mark.asyncio
async def test_no_active_tasks_does_not_wait(shutdown):
    namespace, run = shutdown

    async def wait(*_args, **_kwargs):
        raise AssertionError("empty shutdown must not wait")

    namespace["asyncio"] = SimpleNamespace(wait=wait, CancelledError=asyncio.CancelledError)
    await run([None] * 9)


@pytest.mark.asyncio
async def test_shared_wait_cancellation_propagates_after_initial_task_cancels(shutdown):
    namespace, run = shutdown
    events = []
    first = Task("first", events)
    second = Task("second", events)
    failure = asyncio.CancelledError()

    async def wait(*_args, **_kwargs):
        raise failure

    namespace["asyncio"] = SimpleNamespace(wait=wait, CancelledError=asyncio.CancelledError)
    with pytest.raises(asyncio.CancelledError) as caught:
        await run([first, second, *([None] * 7)])
    assert caught.value is failure
    assert [name for action, name in events if action == "cancel"] == ["first", "second"]


@pytest.mark.asyncio
async def test_real_tasks_finish_cancel_or_fail_with_one_wait_and_no_leak(monkeypatch):
    entered = asyncio.Event()
    started = 0

    async def work(mode):
        nonlocal started
        started += 1
        if started == 3:
            entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            if mode == "complete":
                return
            if mode == "error":
                raise RuntimeError("synthetic cleanup error") from None
            raise

    tasks = [asyncio.create_task(work(mode)) for mode in ("cancel", "complete", "error")]
    log = SimpleNamespace(info=Mock(), warning=Mock())
    monkeypatch.setattr(runtime_task_shutdown, "logger", log)
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        await runtime_task_shutdown.cancel_and_wait_runtime_tasks([
            (str(index), task) for index, task in enumerate(tasks)
        ])
        assert all(task.done() for task in tasks)
        assert tasks[0].cancelled()
        assert tasks[1].result() is None
        assert isinstance(tasks[2].exception(), RuntimeError)
        assert log.info.call_count == 2
        log.warning.assert_called_once()
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
