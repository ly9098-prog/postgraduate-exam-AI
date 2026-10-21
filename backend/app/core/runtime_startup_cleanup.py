"""Classify standalone startup failures and preserve their identity."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Protocol


class StartupResources(Protocol):
    role: str


async def cleanup_failed_startup(
    cleanup: Callable[[], Awaitable[None]],
    *,
    role: str,
    logger: logging.Logger,
) -> None:
    """Run cleanup without replacing the startup exception already in flight."""
    try:
        await cleanup()
    except (Exception, asyncio.CancelledError) as exc:
        try:
            logger.warning("Role %s startup cleanup failed: %s", role, exc, exc_info=True)
        except (Exception, asyncio.CancelledError):
            pass


async def rethrow_startup_failure(
    error: Exception,
    resources: StartupResources,
    shutdown: Callable[[StartupResources], Awaitable[None]],
    *,
    logger: logging.Logger,
) -> None:
    """Run cleanup, then retain the runner's existing SystemError boundary."""
    try:
        logger.critical("Role %s initialization failed: %s", resources.role, error)
    except (Exception, asyncio.CancelledError):
        pass
    if isinstance(error, SystemError):
        raise error
    await cleanup_failed_startup(
        lambda: shutdown(resources),
        role=resources.role,
        logger=logger,
    )
    raise SystemError(
        f"Role {resources.role} initialization failed: {error}"
    ) from error


__all__ = ["StartupResources", "cleanup_failed_startup", "rethrow_startup_failure"]
