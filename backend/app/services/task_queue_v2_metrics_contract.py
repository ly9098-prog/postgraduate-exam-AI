"""Aggregate v2 queue depths onto the historical metrics snapshot."""

from __future__ import annotations

from typing import Any, Awaitable, Callable


async def build_v2_metrics_snapshot(
    *,
    base_metrics: dict[str, int],
    task_types: list[str],
    ready_length: Callable[[str], Awaitable[int]],
    processing_length: Callable[[str], Awaitable[int]],
    retry_length: Callable[[str], Awaitable[int]],
    dead_length: Callable[[str], Awaitable[int]],
) -> dict[str, Any]:
    """Return a copied metrics snapshot with aggregated v2 depths."""
    results = dict(base_metrics)
    ready = 0
    processing = 0
    retry_count = 0
    dead = 0

    for task_type in task_types:
        ready += await ready_length(task_type)
        processing += await processing_length(task_type)
        retry_count += await retry_length(task_type)
        dead += await dead_length(task_type)

    results["ready"] = ready
    results["processing"] = processing
    results["retry"] = retry_count
    results["dead"] = dead
    return results
