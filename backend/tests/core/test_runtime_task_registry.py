"""Managed task contracts with real asyncio ownership and controlled deadlines."""

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.core.runtime_task_registry_probe import task_classes


@pytest.fixture
def ports(monkeypatch):
    logger = Mock()
    return SimpleNamespace(classes=task_classes(monkeypatch, logger), logger=logger)


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "error", "cancel"])
async def test_task_creation_name_and_completion_callback_use_original_error_policy(ports, outcome):
    error = RuntimeError("synthetic task error")

    async def run():
        if outcome == "error":
            raise error
        if outcome == "cancel":
            await asyncio.Future()
        return "synthetic-result"

    managed = ports.classes.ManagedTask.create(run(), "synthetic-task")
    assert managed.name == managed._task.get_name() == "synthetic-task"
    await asyncio.sleep(0)
    if outcome == "cancel":
        managed.cancel()
    await asyncio.gather(managed._task, return_exceptions=True)
    await asyncio.sleep(0)
    if outcome == "error":
        assert managed._task.exception() is error
        ports.logger.error.assert_called_once_with(
            "Background task %s failed: %s: %s", "synthetic-task", "RuntimeError", error,
        )
    else:
        ports.logger.error.assert_not_called()
    managed.cancel()
    assert managed._task.done()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "error", "cancel", "timeout"])
async def test_managed_wait_keeps_swallow_log_and_timeout_boundaries(ports, outcome):
    error = RuntimeError("synthetic managed failure")

    async def run():
        if outcome == "error":
            raise error
        if outcome in {"cancel", "timeout"}:
            await asyncio.Future()

    managed = ports.classes.ManagedTask.create(run(), "synthetic-wait")
    try:
        if outcome == "cancel":
            managed.cancel()
        assert await managed.wait(timeout=0 if outcome == "timeout" else 1) is None
        if outcome == "error":
            ports.logger.warning.assert_called_once_with(
                "Managed task %s: %s: %s", "synthetic-wait", "RuntimeError", error,
            )
        elif outcome == "timeout":
            ports.logger.warning.assert_called_once_with(
                "Managed task %s: did not stop within %ss grace", "synthetic-wait", 0,
            )
        else:
            ports.logger.warning.assert_not_called()
    finally:
        managed.cancel()
        await asyncio.gather(managed._task, return_exceptions=True)


@pytest.mark.asyncio
async def test_registry_register_and_create_preserve_insertion_order_and_only_cancel_live_tasks(ports):
    registry = ports.classes.TaskRegistry()
    first = registry.create(asyncio.sleep(0), "complete")
    await first._task
    second = registry.create(asyncio.sleep(3600), "second")
    third = ports.classes.ManagedTask.create(asyncio.sleep(3600), "third")
    registry.register(third)
    try:
        assert len(registry) == 3
        assert registry._tasks == [first, second, third]
        assert registry.cancel_all() == [second, third]
        await asyncio.gather(second._task, third._task, return_exceptions=True)
        assert registry.cancel_all() == []
    finally:
        await registry.wait_all(timeout=1)


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [0, 1, 3])
async def test_registry_wait_uses_one_shared_wait_and_original_timeout(monkeypatch, ports, size):
    registry = ports.classes.TaskRegistry()
    for index in range(size):
        registry.create(asyncio.sleep(3600), f"task-{index}")
    calls = []
    original = asyncio.wait

    async def wait(tasks, *, timeout):
        calls.append((tasks, timeout))
        return await original(tasks, timeout=timeout)

    monkeypatch.setattr(asyncio, "wait", wait)
    await registry.wait_all(timeout=1)
    assert len(calls) == int(size > 0)
    if size:
        assert calls[0] == ({item._task for item in registry._tasks}, 1)
    assert all(item._task.done() for item in registry._tasks)
    ports.logger.warning.assert_not_called()


@pytest.mark.asyncio
async def test_pending_tasks_share_deadline_log_sorted_names_and_receive_second_cancel(ports):
    registry = ports.classes.TaskRegistry()
    first_cancel = []

    async def stubborn(name):
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            first_cancel.append(name)
            await asyncio.Future()

    for name in ["z-task", "a-task"]:
        registry.create(stubborn(name), name)
    await asyncio.sleep(0)
    try:
        await registry.wait_all(timeout=0)
        assert sorted(first_cancel) == ["a-task", "z-task"]
        ports.logger.warning.assert_called_once_with(
            "Managed tasks did not stop within %ss grace: %s", 0, ["a-task", "z-task"],
        )
        await asyncio.gather(*(item._task for item in registry._tasks), return_exceptions=True)
        assert all(item._task.cancelled() for item in registry._tasks)
    finally:
        for item in registry._tasks:
            item.cancel()
        await asyncio.gather(*(item._task for item in registry._tasks), return_exceptions=True)


@pytest.mark.asyncio
async def test_cancelling_shared_wait_propagates_before_warning_or_retry(monkeypatch, ports):
    registry = ports.classes.TaskRegistry()
    registry.create(asyncio.sleep(3600), "synthetic-task")
    error = asyncio.CancelledError("synthetic wait cancellation")

    async def wait(tasks, *, timeout):
        raise error

    monkeypatch.setattr(asyncio, "wait", wait)
    try:
        with pytest.raises(asyncio.CancelledError) as caught:
            await registry.wait_all()
        assert caught.value is error
        ports.logger.warning.assert_not_called()
    finally:
        await asyncio.gather(*(item._task for item in registry._tasks), return_exceptions=True)


@pytest.mark.asyncio
async def test_managed_wait_swallows_actual_waiter_cancellation_as_before(ports):
    managed = ports.classes.ManagedTask.create(asyncio.sleep(3600), "synthetic-child")
    waiter = asyncio.create_task(managed.wait())
    try:
        await asyncio.sleep(0)
        waiter.cancel()
        assert await waiter is None
        assert managed._task.cancelled()
        ports.logger.warning.assert_not_called()
    finally:
        if not waiter.done():
            waiter.cancel()
        managed.cancel()
        await asyncio.gather(waiter, managed._task, return_exceptions=True)
