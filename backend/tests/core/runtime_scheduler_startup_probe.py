"""Resolve the shared scheduler startup implementation directly."""

from app.services import runtime_scheduler_startup


def scheduler_operations():
    return runtime_scheduler_startup
