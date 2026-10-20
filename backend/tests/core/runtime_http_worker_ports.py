"""Own all controlled tasks and coroutines created by worker startup tests."""

import asyncio
import socket
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest_asyncio

from tests.core.runtime_http_worker_probe import http_worker_operations


@pytest_asyncio.fixture
async def worker_ports(monkeypatch):
    operations = http_worker_operations()
    state = SimpleNamespace(
        operations=operations, tasks=operations.state(), events=[], created=[], rejected=[],
        failed=None, error=None, logger=Mock(), report=Mock(), network=[],
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

    async def prewarm():
        check("prewarm")

    def info(*args):
        check("log")

    def forbid(*args, **kwargs):
        state.network.append("connect")
        raise AssertionError("worker startup contract must not connect externally")

    state.logger.info.side_effect = info
    monkeypatch.setattr(operations.owner, "asyncio", SimpleNamespace(create_task=create))
    monkeypatch.setitem(sys.modules, "app.services.task_queue_worker", SimpleNamespace(
        run_dispatcher_v2=lambda: factory("dispatcher"),
        run_reaper_loop_v2=lambda: factory("reaper"),
    ))
    monkeypatch.setitem(sys.modules, "app.services.ai_prewarm_worker", SimpleNamespace(
        start_worker=prewarm,
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
