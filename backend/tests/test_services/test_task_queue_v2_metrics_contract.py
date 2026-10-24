"""Compatibility baseline for v2 queue metric aggregation."""

from __future__ import annotations

import pytest

from app.services.task_queue_v2_metrics_contract import build_v2_metrics_snapshot


async def provider(values: dict[str, int]):
    async def get(task_type: str) -> int:
        return values.get(task_type, 0)

    return get


@pytest.mark.asyncio
async def test_empty_types_copy_counters_and_zero_depths():
    snapshot = await build_v2_metrics_snapshot(
        base_metrics={"owner_fencing_rejected": 3},
        task_types=[],
        ready_length=await provider({}),
        processing_length=await provider({}),
        retry_length=await provider({}),
        dead_length=await provider({}),
    )

    assert snapshot == {
        "owner_fencing_rejected": 3,
        "ready": 0,
        "processing": 0,
        "retry": 0,
        "dead": 0,
    }


@pytest.mark.asyncio
async def test_multiple_types_are_aggregated_and_base_is_copied():
    ready = await provider({"a": 2, "b": 3})
    processing = await provider({"a": 1, "b": 4})
    retry = await provider({"a": 5, "b": 6})
    dead = await provider({"a": 7, "b": 8})
    base = {"reaper_reclaimed": 9, "enqueue_rejected": 1}

    snapshot = await build_v2_metrics_snapshot(
        base_metrics=base,
        task_types=["a", "b"],
        ready_length=ready,
        processing_length=processing,
        retry_length=retry,
        dead_length=dead,
    )

    assert snapshot["ready"] == 5
    assert snapshot["processing"] == 5
    assert snapshot["retry"] == 11
    assert snapshot["dead"] == 15
    assert snapshot["reaper_reclaimed"] == 9
    assert base == {"reaper_reclaimed": 9, "enqueue_rejected": 1}
