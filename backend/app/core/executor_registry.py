"""Executor registry — set during application lifespan, read at call sites.

Avoids threading executor references through deeply nested function signatures
while still respecting the ``no import-time global thread pool`` constraint.

Usage::

    # In main.py lifespan startup:
    executors = init_executors_for_role(role)
    init_executor_registry(executors)

    # In any worker/service function:
    from app.core.executor_registry import get_executor
    result = await get_executor("image").run(blocking_fn, arg)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.bounded_executor import BoundedExecutor

_executors: dict[str, BoundedExecutor] = {}


def init_executor_registry(executors: dict[str, BoundedExecutor]) -> None:
    """Set the global executor instances. Called once during lifespan startup."""
    _executors.clear()
    _executors.update(executors)


def get_executor(name: str) -> BoundedExecutor:
    """Return the named executor. Raises KeyError if not registered."""
    return _executors[name]


def get_all_executors() -> dict[str, BoundedExecutor]:
    """Return a copy of all registered executors (for shutdown)."""
    return dict(_executors)


def clear_executor_registry() -> None:
    """Remove all executor references (for shutdown cleanup)."""
    _executors.clear()
