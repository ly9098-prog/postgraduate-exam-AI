"""Compatibility baseline for v2 claim validation and task materialization."""

from __future__ import annotations

import json

from app.services.task_queue_contract import Task, TaskStatus
from app.services.task_queue_v2_claim_contract import (
    build_v2_claimed_task,
    v2_dequeue_unavailable,
)


def claim(task: Task, overrides=None):
    values = [
        task.task_id,
        json.dumps(task.to_dict()),
        "stored-owner",
        "42",
        "123.5",
    ]
    if overrides:
        for index, value in overrides.items():
            values[index] = value
    return values


def test_materializes_a_valid_claim_with_server_ownership():
    source = Task(task_id="task-1", task_type="demo", payload={"value": 1})
    result = build_v2_claimed_task(
        claim(source),
        task_type="demo",
        owner_token="new-owner",
    )

    assert result.corrupt_error is None
    assert result.task is not None
    assert result.task.task_id == "task-1"
    assert result.task.status is TaskStatus.PROCESSING
    assert result.task.owner_token == "stored-owner"
    assert result.task.generation == 42
    assert result.task.lease_expires_at == 123.5


def test_falls_back_to_new_owner_and_zeroed_lease_fields():
    source = Task(task_id="task-1", task_type="demo", payload={})
    result = build_v2_claimed_task(
        claim(source, {2: None, 3: None, 4: None}),
        task_type="demo",
        owner_token="new-owner",
    )

    assert result.task.owner_token == "new-owner"
    assert result.task.generation == 0
    assert result.task.lease_expires_at == 0.0


def test_reports_invalid_json_and_identity_mismatch_for_corruption():
    source = Task(task_id="task-1", task_type="demo", payload={})
    invalid_json = claim(source)
    invalid_json[1] = "{invalid"
    result = build_v2_claimed_task(
        invalid_json,
        task_type="demo",
        owner_token="owner",
    )
    assert result.task is None
    assert result.corrupt_error is not None
    assert result.corrupt_error.startswith("task-1:")

    mismatch = claim(Task(task_id="other", task_type="demo", payload={}))
    mismatch[0] = "task-1"
    result = build_v2_claimed_task(
        mismatch,
        task_type="demo",
        owner_token="owner",
    )
    assert result.task is None
    assert "task identity mismatch" in result.corrupt_error


def test_ignores_empty_and_malformed_claim_shapes():
    for value in (None, [], ["task-1"], ["task-1", "{}", "owner", "1", "2", "extra"]):
        result = build_v2_claimed_task(
            value,
            task_type="demo",
            owner_token="owner",
        )
        assert result.task is None
        assert result.corrupt_error is None


def test_unavailable_message_preserves_historical_prefix():
    assert v2_dequeue_unavailable("timeout") == "Redis unavailable during dequeue: timeout"
