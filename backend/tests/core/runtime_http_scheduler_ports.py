"""Own all controlled tasks and coroutines created by scheduler startup tests."""

import asyncio
import socket
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest_asyncio

from tests.core.runtime_http_scheduler_probe import http_scheduler_operations


@pytest_asyncio.fixture
async def scheduler_ports(monkeypatch):
    operations = http_scheduler_operations()
    state = SimpleNamespace(
        operations=operations, tasks=operations.state(), events=[], created=[],
        rejected=[], failed=None, error=None, logger=Mock(), report=Mock(),
        network=[], enqueue=None,
    )
    create_task = asyncio.create_task

    def check(stage):
        state.events.append(stage)
        if state.failed == stage:
            raise state.error

    async def loop(label):
        state.events.append("run:" + label)
        try:
            await asyncio.Future()
        finally:
            state.events.append("end:" + label)

    def factory(label):
        check("factory:" + label)
        return loop(label)

    def create(coroutine, *, name):
        try:
            check("create:" + name)
        except BaseException:
            state.rejected.append(coroutine)
            raise
        task = create_task(coroutine, name=name)
        state.created.append(task)
        return task

    async def audit_start():
        check("audit.start")

    async def metrics_start():
        check("metrics.start")

    def info(*args, **kwargs):
        state.events.append("log")

    def warn(*args, **kwargs):
        state.events.append("warn")

    def forbid(*args, **kwargs):
        state.network.append("connect")
        raise AssertionError("scheduler startup contract must not connect externally")

    state.logger.info.side_effect = info
    state.logger.warning.side_effect = warn
    monkeypatch.setattr(operations.owner, "asyncio", SimpleNamespace(create_task=create))
    monkeypatch.setitem(sys.modules, "app.services.system_task_service", SimpleNamespace(
        run_scheduler_heartbeat=lambda: factory("heartbeat"),
    ))
    monkeypatch.setitem(sys.modules, "app.services.audit_cleanup_scheduler", SimpleNamespace(
        audit_log_cleanup_scheduler=SimpleNamespace(start=audit_start),
    ))
    monkeypatch.setitem(sys.modules, "app.services.recommendation_metrics_scheduler", SimpleNamespace(
        recommendation_metrics_scheduler=SimpleNamespace(start=metrics_start),
    ))
    from app.services import runtime_periodic_tasks
    monkeypatch.setattr(runtime_periodic_tasks, "run_token_cleanup", lambda: factory("token"))
    monkeypatch.setattr(runtime_periodic_tasks, "run_staging_cleanup", lambda: factory("staging"))
    monkeypatch.setattr(runtime_periodic_tasks, "run_export_processor_loop", lambda *a: factory("export"))
    monkeypatch.setattr(runtime_periodic_tasks, "run_export_cleanup", lambda: factory("export_cleanup"))
    monkeypatch.setitem(sys.modules, "app.services.outbox_service", SimpleNamespace(
        run_outbox_dispatcher=lambda cb: factory("outbox_dispatcher"),
        run_outbox_reconciler=lambda: factory("outbox_reconciler"),
    ))
    monkeypatch.setitem(sys.modules, "app.services.task_queue_service", SimpleNamespace(
        task_queue=SimpleNamespace(),
    ))
    monkeypatch.setattr(socket.socket, "connect", forbid)
    monkeypatch.setattr(socket.socket, "connect_ex", forbid)
    try:
        yield state
    finally:
        for coroutine in state.rejected:
            coroutine.close()
        for task in state.created:
            if not task.done():
                task.cancel()
        await asyncio.gather(*state.created, return_exceptions=True)
        assert all(task.done() for task in state.created)
        assert not state.network
