"""Resolve the real HTTP scheduler startup implementation and state."""

from types import SimpleNamespace

from app.services import runtime_http_scheduler_startup


def http_scheduler_operations():
    return SimpleNamespace(
        state=runtime_http_scheduler_startup.HttpSchedulerTasks,
        start=runtime_http_scheduler_startup.start_http_scheduler_tasks,
        owner=runtime_http_scheduler_startup,
    )
