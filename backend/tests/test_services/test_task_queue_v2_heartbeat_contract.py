"""Compatibility baseline for v2 heartbeat identity and result handling."""

from __future__ import annotations

from app.services.task_queue_contract import Task
from app.services.task_queue_v2_heartbeat_contract import (
    apply_v2_heartbeat_result,
    resolve_v2_heartbeat_identity,
    v2_heartbeat_mismatch,
)


def test_identity_supports_task_tuple_and_string_shapes():
    task = Task(
        task_id="task-1",
        task_type="demo",
        payload={},
        owner_token="owner",
    )
    assert resolve_v2_heartbeat_identity(task) == resolve_v2_heartbeat_identity(
        ("task-1", "demo", "owner")
    )
    assert resolve_v2_heartbeat_identity(
        ("task-1", "hint", "owner"), task_type="demo"
    ).task_type == "demo"
    assert resolve_v2_heartbeat_identity("task-1", task_type="demo").task_type == "demo"


def test_identity_validity_requires_all_fenced_fields():
    assert resolve_v2_heartbeat_identity(
        ("task-1", "demo", "owner")
    ).is_valid()
    assert not resolve_v2_heartbeat_identity(("task-1", "demo", "")).is_valid()
    assert not resolve_v2_heartbeat_identity(("task-1", "", "owner")).is_valid()
    assert not resolve_v2_heartbeat_identity(("", "demo", "owner")).is_valid()


def test_apply_result_updates_only_accepted_task_instances():
    task = Task(task_id="task-1", task_type="demo", payload={})
    apply_v2_heartbeat_result(task, result=0, lease_sec=30, now=100.0)
    assert task.lease_expires_at == 0.0

    apply_v2_heartbeat_result(task, result=1, lease_sec=30, now=100.0)
    assert task.lease_expires_at == 130.0

    apply_v2_heartbeat_result("task-1", result=1, lease_sec=30, now=100.0)


def test_mismatch_mapping_preserves_fencing_labels():
    assert v2_heartbeat_mismatch(0) == "owner"
    assert v2_heartbeat_mismatch(-1) == "generation"
    assert v2_heartbeat_mismatch(1) is None
