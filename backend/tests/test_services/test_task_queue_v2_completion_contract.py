"""Compatibility baseline for v2 completion payload preparation."""

from __future__ import annotations

import json

from app.services.task_queue_contract import Task, TaskStatus
from app.services.task_queue_v2_completion_contract import (
    apply_v2_completed_result,
    build_v2_completed_payload,
    v2_complete_unavailable,
)


def test_task_payload_resets_runtime_fields_and_preserves_identity():
    source = Task(
        task_id="task-1",
        task_type="demo",
        payload={"value": 1},
        status=TaskStatus.PROCESSING,
        owner_token="owner",
        error="temporary",
    )
    payload = json.loads(
        build_v2_completed_payload(source, updated_at=123.0)
    )

    assert payload["task_id"] == "task-1"
    assert payload["task_type"] == "demo"
    assert payload["payload"] == {"value": 1}
    assert payload["status"] == "completed"
    assert payload["updated_at"] == 123.0
    assert payload["lease_expires_at"] == 0.0
    assert payload["owner_token"] == ""
    assert payload["error"] == ""
    assert source.status is TaskStatus.PROCESSING


def test_string_payload_uses_current_hash_data_when_available():
    current = json.dumps(
        {
            "task_id": "task-1",
            "task_type": "demo",
            "payload": {"value": 2},
            "status": "processing",
        }
    )
    payload = json.loads(
        build_v2_completed_payload(
            "task-1",
            task_type="demo",
            current_payload=current,
            updated_at=456.0,
        )
    )

    assert payload["payload"] == {"value": 2}
    assert payload["status"] == "completed"
    assert payload["updated_at"] == 456.0
    assert payload["owner_token"] == ""


def test_string_payload_falls_back_to_minimal_shape():
    payload = json.loads(
        build_v2_completed_payload(
            "task-1",
            task_type="demo",
            current_payload=None,
            updated_at=789.0,
        )
    )

    assert payload == {
        "task_id": "task-1",
        "task_type": "demo",
        "payload": {},
        "status": "completed",
        "updated_at": 789.0,
        "lease_expires_at": 0.0,
        "owner_token": "",
        "error": "",
    }


def test_apply_result_only_updates_task_instances():
    source = Task(
        task_id="task-1",
        task_type="demo",
        payload={},
        owner_token="owner",
        error="temporary",
    )
    apply_v2_completed_result(source, updated_at=123.0)
    assert source.status is TaskStatus.COMPLETED
    assert source.updated_at == 123.0
    assert source.lease_expires_at == 0.0
    assert source.error == ""

    apply_v2_completed_result("task-1", updated_at=123.0)


def test_unavailable_message_preserves_historical_prefix():
    assert (
        v2_complete_unavailable("timeout")
        == "Redis unavailable during complete: timeout"
    )
