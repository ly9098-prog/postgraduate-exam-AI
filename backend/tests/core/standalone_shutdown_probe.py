"""Resolve the actual standalone resource shutdown implementation."""

from app.core import standalone_runtime_shutdown


def shutdown_operations():
    return standalone_runtime_shutdown
