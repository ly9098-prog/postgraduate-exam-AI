"""Characterize shared-resource shutdown order and exception boundaries."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app import main
from app.core.runtime_resource_shutdown import (
    close_runtime_connections,
    shutdown_render_resources,
    stop_resource_reconciler,
)

PORTS = ["executors", "registry", "pdf", "queue", "ai", "budget", "database", "orphans"]


@pytest.fixture
def shutdown():
    async def close():
        await shutdown_render_resources()
        await close_runtime_connections()
        await stop_resource_reconciler()
    return close


@pytest.fixture
def ports(monkeypatch):
    from app.core import (
        ai_runtime_guard,
        database,
        executor_registry,
        executors,
        resource_guard,
    )
    from app.features import token_budget
    from app.services import pdf_renderer_service, task_queue_service

    events = []
    controls = {}

    def sync(name):
        def call(*args):
            events.append((name, args))
        controls[name] = Mock(side_effect=call)
        return controls[name]

    def asynchronous(name):
        async def call(*args):
            events.append((name, args))
        controls[name] = AsyncMock(side_effect=call)
        return controls[name]

    registry = {"synthetic": object()}
    monkeypatch.setattr(executor_registry, "get_all_executors", lambda: registry)
    monkeypatch.setattr(executor_registry, "clear_executor_registry", sync("registry"))
    monkeypatch.setattr(executors, "shutdown_executors", asynchronous("executors"))
    monkeypatch.setattr(pdf_renderer_service.pdf_renderer, "shutdown", asynchronous("pdf"))
    monkeypatch.setattr(task_queue_service.task_queue, "close", asynchronous("queue"))
    monkeypatch.setattr(ai_runtime_guard.ai_runtime_guard, "close", asynchronous("ai"))
    monkeypatch.setattr(token_budget, "close_token_budget", asynchronous("budget"))
    monkeypatch.setattr(database, "engine", SimpleNamespace(dispose=asynchronous("database")))
    monkeypatch.setattr(resource_guard.resource_guard, "stop_orphan_reconciler", asynchronous("orphans"))
    warning = Mock()
    monkeypatch.setattr(main.logger, "warning", warning)
    return SimpleNamespace(events=events, controls=controls, registry=registry, warning=warning)


@pytest.mark.asyncio
async def test_shared_shutdown_order_and_original_registry_object(shutdown, ports):
    await shutdown()
    assert [name for name, _args in ports.events] == PORTS
    assert ports.events[0][1] == (ports.registry,)
    ports.warning.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", PORTS)
async def test_ordinary_error_continues_at_next_original_resource_boundary(shutdown, ports, failed):
    ports.controls[failed].side_effect = RuntimeError("synthetic resource failure")
    await shutdown()
    skipped = {failed}
    if failed == "executors":
        skipped.add("registry")
    if failed == "ai":
        skipped.add("budget")
    assert [name for name, _args in ports.events] == [name for name in PORTS if name not in skipped]
    ports.warning.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", PORTS)
async def test_cancellation_propagates_and_stops_later_cleanup(shutdown, ports, failed):
    cancelled = asyncio.CancelledError()
    ports.controls[failed].side_effect = cancelled
    with pytest.raises(asyncio.CancelledError) as caught:
        await shutdown()
    assert caught.value is cancelled
    assert [name for name, _args in ports.events] == PORTS[:PORTS.index(failed)]
    ports.warning.assert_not_called()
