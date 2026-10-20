"""Resolve the real HTTP worker startup implementation and reference state."""

from types import SimpleNamespace

from app.services import runtime_http_worker_startup


def http_worker_operations():
    return SimpleNamespace(
        state=runtime_http_worker_startup.HttpWorkerTasks,
        start=runtime_http_worker_startup.start_http_worker_tasks,
        owner=runtime_http_worker_startup,
    )
