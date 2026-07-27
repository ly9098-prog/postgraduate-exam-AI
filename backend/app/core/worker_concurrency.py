"""Shared worker concurrency gate — ensures WORKER_CONCURRENCY limits ALL heavy tasks.

Both the pipeline dispatcher and AI prewarm worker acquire from this gate,
so setting ``WORKER_CONCURRENCY=1`` limits to at most one heavy task at any
time across all task types.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.config import settings

logger = logging.getLogger("postgraduate-ai.worker-concurrency")

# Module-level semaphore — shared across dispatcher and prewarm worker
_worker_semaphore: asyncio.Semaphore | None = None


def get_worker_semaphore() -> asyncio.Semaphore:
    """Get or create the shared worker semaphore.

    The capacity is ``WORKER_CONCURRENCY`` (default 1). Returns a bound
    semaphore for ``async with`` usage.
    """
    global _worker_semaphore
    if _worker_semaphore is None:
        _worker_semaphore = asyncio.Semaphore(settings.WORKER_CONCURRENCY)
        logger.info(
            "Worker concurrency gate initialized: concurrency=%d",
            settings.WORKER_CONCURRENCY,
        )
    return _worker_semaphore


async def reset_worker_semaphore() -> None:
    """Reset the worker semaphore (for testing)."""
    global _worker_semaphore
    _worker_semaphore = None
