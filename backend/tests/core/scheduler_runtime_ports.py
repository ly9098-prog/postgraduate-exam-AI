"""Isolate standalone scheduler startup while retaining real managed tasks."""

import asyncio
import socket
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest_asyncio

from app.core import bootstrap, deployment_profile, runtime_task_registry


@pytest_asyncio.fixture
async def scheduler(monkeypatch):
    events, failures, attempts = [], {}, []
    registry = bootstrap.TaskRegistry()
    state = SimpleNamespace(
        events=events, failures=failures, registry=registry, enqueue=None,
        profile=deployment_profile.DeploymentProfile.LOCAL_IMPORT,
    )

    async def loop(*args):
        await asyncio.Future()

    async def start(name):
        events.append(name)
        if name in failures:
            raise failures[name]

    async def enqueue(*args, **kwargs):
        events.append(("enqueue", args, kwargs))
        return "synthetic-enqueued"

    def outbox(callback):
        state.enqueue = callback
        return loop()

    def forbid(*args, **kwargs):
        attempts.append("connect")
        raise AssertionError("scheduler startup must not connect to external services")

    monkeypatch.setattr(socket.socket, "connect", forbid)
    monkeypatch.setattr(socket.socket, "connect_ex", forbid)
    monkeypatch.setattr(bootstrap.settings, "APP_ENV", "test")
    monkeypatch.setattr(deployment_profile, "detect_deployment_profile", lambda: state.profile)
    logger = Mock()
    monkeypatch.setattr(bootstrap, "logger", logger)
    monkeypatch.setattr(runtime_task_registry, "logger", logger)
    state.logger = logger
    for name in ["run_token_cleanup", "run_staging_cleanup", "run_export_processor_loop", "run_export_cleanup"]:
        monkeypatch.setattr(bootstrap, name, loop)
    _install_scheduler_modules(monkeypatch, loop, start, outbox, enqueue)
    try:
        yield state
    finally:
        await registry.wait_all(timeout=1)
        assert all(managed._task.done() for managed in registry._tasks)
        assert not attempts, "scheduler swallowed an attempted connection"


def _install_scheduler_modules(monkeypatch, loop, start, outbox, enqueue):
    modules = {
        "app.services.system_task_service": SimpleNamespace(run_scheduler_heartbeat=loop),
        "app.services.audit_cleanup_scheduler": SimpleNamespace(
            audit_log_cleanup_scheduler=SimpleNamespace(start=lambda: start("audit")),
        ),
        "app.services.recommendation_metrics_scheduler": SimpleNamespace(
            recommendation_metrics_scheduler=SimpleNamespace(start=lambda: start("metrics")),
        ),
        "app.services.outbox_service": SimpleNamespace(run_outbox_dispatcher=outbox, run_outbox_reconciler=loop),
        "app.services.task_queue_service": SimpleNamespace(task_queue=SimpleNamespace(enqueue_v2=enqueue)),
        "app.services.practice.projection_reconciliation_service": SimpleNamespace(run_answer_projection_reconciler=loop),
        "app.services.task_observability_service": SimpleNamespace(run_task_health_monitor=loop),
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
