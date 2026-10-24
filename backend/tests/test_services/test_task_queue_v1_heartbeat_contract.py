"""Compatibility baseline for v1 heartbeat identity and result handling."""

from __future__ import annotations

from app.services.task_queue_contract import Task
from app.services.task_queue_v1_heartbeat_contract import (
    apply_v1_heartbeat_result,
    resolve_v1_heartbeat_identity,
    v1_heartbeat_expiry,
)


def test_identity_supports_task_tuple_and_string_shapes():
    task = Task(
        task_id="task-1",
        task_type="demo",
        payload={},
        owner_token="owner",
    )
    assert resolve_v1_heartbeat_identity(task) == resolve_v1_heartbeat_identity(
        ("task-1", "demo", "owner")
    )
    assert resolve_v1_heartbeat_identity(
        ("task-1", "hint", "owner"), task_type="demo"
    ).task_type == "demo"
    assert resolve_v1_heartbeat_identity("task-1", task_type="demo").owner_token == ""


def test_identity_validity_and_legacy_fencing_mode():
    assert resolve_v1_heartbeat_identity(("task-1", "demo", "")).is_valid()
    assert not resolve_v1_heartbeat_identity(("task-1", "", "")).is_valid()
    assert not resolve_v1_heartbeat_identity(("", "demo", "")).is_valid()
    assert resolve_v1_heartbeat_identity(("task-1", "demo", "owner")).fenced
    assert not resolve_v1_heartbeat_identity(("task-1", "demo", "")).fenced


def test_apply_result_updates_task_only_when_accepted():
    task = Task(task_id="task-1", task_type="demo", payload={})
    assert apply_v1_heartbeat_result(task, result=0, lease_expires_at=100.0) is False
    assert task.lease_expires_at == 0.0

    assert apply_v1_heartbeat_result(task, result=1, lease_expires_at=100.0) is True
    assert task.lease_expires_at == 100.0
    assert apply_v1_heartbeat_result("task-1", result=1, lease_expires_at=100.0) is True


def test_expiry_uses_now_plus_lease():
    assert v1_heartbeat_expiry(30, now=100.0) == 130.0
