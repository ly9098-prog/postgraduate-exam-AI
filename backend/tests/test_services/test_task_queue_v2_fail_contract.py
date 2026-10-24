"""Compatibility baseline for v2 task failure payload preparation."""

from __future__ import annotations

import json

from app.services.task_queue_contract import Task, TaskStatus
from app.services.task_queue_v2_fail_contract import (
    V2FailIdentity,
    apply_v2_dead_result,
    apply_v2_retry_result,
    build_v2_dead_plan,
    build_v2_retry_plan,
    resolve_v2_fail_identity,
    v2_fail_transition,
)


def task(**overrides):
    values = dict(
        task_id="task-1",
        task_type="demo",
        payload={"value": 1},
        owner_token="owner",
        retry_count=1,
        max_retries=3,
    )
    values.update(overrides)
    return Task(**values)


def test_identity_requires_task_type_and_owner_token():
    assert resolve_v2_fail_identity(task()) == V2FailIdentity(
        task_id="task-1", task_type="demo", owner_token="owner"
    )
    assert resolve_v2_fail_identity("task-1", task_type="demo") == V2FailIdentity(
        task_id="task-1", task_type="demo", owner_token=""
    )
    assert resolve_v2_fail_identity("task-1") == V2FailIdentity(
        task_id="task-1", task_type="", owner_token=""
    )


def test_retry_plan_payload_and_exponential_delay():
    original = task()
    plan = build_v2_retry_plan(original, "temporary", base_delay=10)
    data = json.loads(plan.task_json)

    assert plan.retry_count == 2
    assert plan.max_retries == 3
    assert plan.delay == 20
    assert data["status"] == "failed"
    assert data["retry_count"] == 2
    assert data["error"] == "temporary"
    assert data["owner_token"] == ""
    assert data["lease_expires_at"] == 0.0
    assert data["updated_at"] == plan.updated_at
    assert original.retry_count == 1


def test_dead_plan_preserves_task_and_string_shapes():
    original = task()
    plan = build_v2_dead_plan(original, "fatal", retry_count=4)
    data = json.loads(plan.task_json)

    assert data["status"] == "dead"
    assert data["retry_count"] == 4
    assert data["error"] == "fatal"
    assert data["owner_token"] == ""
    assert data["updated_at"] == plan.updated_at

    string_plan = build_v2_dead_plan("task-2", "fatal", retry_count=0, task_type="demo")
    assert json.loads(string_plan.task_json) == {
        "task_id": "task-2",
        "task_type": "demo",
        "payload": {},
        "status": "dead",
    }


def test_dead_plan_can_reuse_retry_timestamp():
    retry_plan = build_v2_retry_plan(task(), "retry full", base_delay=10)
    dead_plan = build_v2_dead_plan(
        task(),
        "retry full",
        retry_count=retry_plan.retry_count,
        updated_at=retry_plan.updated_at,
    )

    assert dead_plan.updated_at == retry_plan.updated_at
    assert json.loads(dead_plan.task_json)["updated_at"] == retry_plan.updated_at


def test_result_application_and_transition_mapping():
    original = task()
    retry_plan = build_v2_retry_plan(original, "temporary", base_delay=10)
    apply_v2_retry_result(original, retry_plan, "temporary")

    assert original.retry_count == 2
    assert original.status is TaskStatus.FAILED
    assert original.error == "temporary"
    assert original.updated_at == retry_plan.updated_at
    assert original.lease_expires_at == 0.0

    dead_plan = build_v2_dead_plan(original, "fatal", retry_count=3)
    apply_v2_dead_result(original, dead_plan, "fatal")

    assert original.status is TaskStatus.DEAD
    assert original.retry_count == 3
    assert original.updated_at == dead_plan.updated_at

    assert v2_fail_transition(1, retry_count=2, max_retries=3) == "retry"
    assert v2_fail_transition(1, retry_count=3, max_retries=3) == "dead"
    assert v2_fail_transition(2, retry_count=1, max_retries=3) == "dead"
    assert v2_fail_transition(0, retry_count=1, max_retries=3) is None
    assert v2_fail_transition(-1, retry_count=1, max_retries=3) is None
