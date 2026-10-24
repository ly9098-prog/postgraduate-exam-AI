"""Compatibility baseline for v1 claim task materialization."""

from __future__ import annotations

import json

from app.services.task_queue_contract import Task, TaskStatus
from app.services.task_queue_v1_claim_contract import (
    build_v1_claimed_task,
    build_v1_retry_claimed_task,
)


def claim_result(task_id="task-1", owner="stored", generation="42"):
    task = Task(task_id=task_id, task_type="demo", payload={"value": 1})
    return [json.dumps(task.to_dict()), owner, generation]


def test_ready_claim_materializes_processing_task_with_server_ownership():
    task = build_v1_claimed_task(
        claim_result(),
        owner_token="new-owner",
        lease_expiry=100.0,
        generation=1,
        now=90.0,
    )

    assert task is not None
    assert task.status is TaskStatus.PROCESSING
    assert task.lease_expires_at == 100.0
    assert task.owner_token == "stored"
    assert task.generation == 42
    assert task.updated_at == 90.0


def test_ready_claim_falls_back_to_request_context_and_maps_none():
    task = build_v1_claimed_task(
        claim_result(owner=None, generation=None),
        owner_token="new-owner",
        lease_expiry=100.0,
        generation=7,
        now=90.0,
    )
    assert task.owner_token == "new-owner"
    assert task.generation == 7
    assert build_v1_claimed_task(
        None,
        owner_token="new-owner",
        lease_expiry=100.0,
        generation=7,
    ) is None


def test_retry_claim_materializes_task_and_preserves_fallbacks():
    raw, token, generation = claim_result()
    task = build_v1_retry_claimed_task(
        [raw, "task-1", token, generation],
        owner_token="new-owner",
        generation=7,
        lease_sec=30,
        now=100.0,
    )
    assert task is not None
    assert task.status is TaskStatus.PROCESSING
    assert task.lease_expires_at == 130.0
    assert task.owner_token == "stored"
    assert task.generation == 42
    assert task.updated_at == 100.0

    fallback = build_v1_retry_claimed_task(
        [raw, "task-1", "", ""],
        owner_token="new-owner",
        generation=7,
        lease_sec=30,
        now=100.0,
    )
    assert fallback.owner_token == "new-owner"
    assert fallback.generation == 7
    assert build_v1_retry_claimed_task(
        None,
        owner_token="new-owner",
        generation=7,
        lease_sec=30,
    ) is None
