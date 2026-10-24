"""Compatibility baseline for v1 complete/fail transition preparation."""

from __future__ import annotations

import json

from app.services.task_queue_contract import Task, TaskStatus
from app.services.task_queue_v1_transition_contract import (
    apply_v1_failure_attempt,
    apply_v1_local_retry,
    build_v1_fail_dead_payload,
    prepare_v1_retry_task,
    resolve_v1_transition_identity,
    should_v1_retry,
)


def test_identity_supports_task_and_string_shapes():
    task = Task(
        task_id="task-1",
        task_type="demo",
        payload={},
        owner_token="owner",
    )
    assert resolve_v1_transition_identity(task).owner_token == "owner"
    identity = resolve_v1_transition_identity("task-1", task_type="demo")
    assert identity.task_id == "task-1"
    assert identity.task_type == "demo"
    assert identity.owner_token == ""
    assert identity.is_valid()
    assert not resolve_v1_transition_identity("task-1").is_valid()


def test_failure_attempt_updates_only_task_instances():
    task = Task(
        task_id="task-1",
        task_type="demo",
        payload={},
        retry_count=1,
        max_retries=3,
    )
    assert apply_v1_failure_attempt(task, "temporary", now=100.0) is True
    assert task.retry_count == 2
    assert task.error == "temporary"
    assert task.updated_at == 100.0
    assert apply_v1_failure_attempt("task-1", "temporary") is False


def test_retry_decision_and_task_preparation():
    task = Task(
        task_id="task-1",
        task_type="demo",
        payload={},
        retry_count=2,
        max_retries=3,
    )
    assert should_v1_retry(task) is True
    prepare_v1_retry_task(task, now=100.0)
    assert task.status is TaskStatus.FAILED
    assert task.updated_at == 100.0

    exhausted = Task(
        task_id="task-1",
        task_type="demo",
        payload={},
        retry_count=3,
        max_retries=3,
    )
    assert should_v1_retry(exhausted) is False
    assert should_v1_retry("task-1") is False


def test_dead_payload_and_local_retry_preserve_historical_shapes():
    task = Task(task_id="task-1", task_type="demo", payload={"value": 1})
    assert json.loads(build_v1_fail_dead_payload(task))["task_id"] == "task-1"
    assert json.loads(build_v1_fail_dead_payload("task-1")) == {"task_id": "task-1"}

    apply_v1_local_retry(task, allow_local_fallback=True)
    assert task.status is TaskStatus.PENDING
    assert task.lease_expires_at == 0
