"""Resolve the real neutral task registry module for isolated contracts."""

from app.core import runtime_task_registry


def task_classes(monkeypatch, logger):
    monkeypatch.setattr(runtime_task_registry, "logger", logger)
    return runtime_task_registry
