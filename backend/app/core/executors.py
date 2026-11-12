"""Role-aware BoundedExecutor containers.

Executors are created during application startup (``lifespan``) per process role.
Import-time instantiation is forbidden — executors must be created when the
process role is known so that capacity settings match the deployment profile.

Usage::

    from app.core.executors import get_executors, init_executors_for_role, shutdown_executors

    # In lifespan startup:
    executors = init_executors_for_role(role)

    # In a handler:
    result = await executors["pdf"].run(fn, arg)

    # In lifespan shutdown:
    await shutdown_executors(executors)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.bounded_executor import BoundedExecutor


def init_executors_for_role(
    role: str, is_production: bool = True
) -> dict[str, BoundedExecutor]:
    """Create BoundedExecutor instances appropriate for *role*.

    Web role gets a small file-I/O executor.
    Worker role gets PDF, image, file-I/O, and formula executors.
    Scheduler role gets only cleanup-level I/O.

    All capacities are conservative bounded-executor defaults; production web
    workers are not tied to a fixed server size and OCR uses a remote API.
    """
    from app.core.bounded_executor import BoundedExecutor

    if role == "web":
        return {
            "file_io": BoundedExecutor(
                "file_io", max_workers=1, max_queued=4, timeout=30
            ),
        }

    if role == "scheduler":
        return {
            "file_io": BoundedExecutor(
                "file_io", max_workers=1, max_queued=2, timeout=30
            ),
        }

    # Worker role (and "all" for dev)
    if is_production:
        pdf_workers = 1
        image_workers = 1
    else:
        pdf_workers = 2
        image_workers = 2

    return {
        "pdf": BoundedExecutor(
            "pdf", max_workers=pdf_workers, max_queued=2, timeout=120
        ),
        "image": BoundedExecutor(
            "image", max_workers=image_workers, max_queued=4, timeout=60
        ),
        "file_io": BoundedExecutor("file_io", max_workers=2, max_queued=8, timeout=30),
        "formula": BoundedExecutor("formula", max_workers=1, max_queued=2, timeout=60),
    }


async def shutdown_executors(executors: dict[str, BoundedExecutor]) -> None:
    """Shut down all executors in reverse-insertion order."""
    names = list(executors.keys())
    for name in reversed(names):
        exec = executors[name]
        if not exec.is_shutdown:
            await exec.shutdown()
