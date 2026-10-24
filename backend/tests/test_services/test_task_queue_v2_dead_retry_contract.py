"""Compatibility baseline for v2 dead-task administrator retry payloads."""

from __future__ import annotations

import json

import pytest

from app.services.task_queue_v2_dead_retry_contract import (
    V2DeadRetryPayloadError,
    build_v2_dead_retry_payload,
    parse_v2_dead_retry_payload,
)


def dead_payload(**overrides):
    values = {
        "task_id": "task-1",
        "task_type": "demo",
        "payload": {"value": 1},
        "status": "dead",
        "retry_count": 3,
        "error": "fatal",
        "schema_version": 2,
        "minimum_worker_version": 1,
        "generation": 7,
    }
    values.update(overrides)
    return values


def test_parse_rejects_corrupt_non_object_and_identity_mismatch_payloads():
    with pytest.raises(V2DeadRetryPayloadError, match="corrupt_payload"):
        parse_v2_dead_retry_payload("{invalid", task_id="task-1", task_type="demo")
    with pytest.raises(V2DeadRetryPayloadError, match="payload_not_object"):
        parse_v2_dead_retry_payload("[]", task_id="task-1", task_type="demo")
    with pytest.raises(V2DeadRetryPayloadError, match="identity_mismatch"):
        parse_v2_dead_retry_payload(
            json.dumps(dead_payload(task_id="other")),
            task_id="task-1",
            task_type="demo",
        )


def test_retry_payload_resets_cycle_and_preserves_generation_and_payload():
    source = dead_payload()
    raw = build_v2_dead_retry_payload(source, task_type="demo", now=123.0)
    data = json.loads(raw)

    assert data["status"] == "pending"
    assert data["retry_count"] == 0
    assert data["error"] == ""
    assert data["updated_at"] == 123.0
    assert data["lease_expires_at"] == 0.0
    assert data["owner_token"] == ""
    assert data["generation"] == 7
    assert data["payload"] == {"value": 1}
    assert data["schema_version"] == 2


def test_retry_payload_raises_worker_floor_without_upgrading_schema():
    source = dead_payload(schema_version=1, minimum_worker_version=1)
    data = json.loads(
        build_v2_dead_retry_payload(source, task_type="demo", now=123.0)
    )
    assert data["schema_version"] == 1
    assert data["minimum_worker_version"] == 1


def test_invalid_schema_version_propagates_for_existing_failure_boundary():
    with pytest.raises(ValueError):
        build_v2_dead_retry_payload(
            dead_payload(schema_version="invalid"),
            task_type="demo",
            now=123.0,
        )
