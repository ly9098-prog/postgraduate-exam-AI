"""Compatibility baseline for v2 dead-task administrator retry payloads."""

from __future__ import annotations

import json

import pytest

from app.services import worker_task_types
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


def test_historical_availability_dead_letter_gets_a_fresh_bounded_retry_budget():
    source = dead_payload(
        task_type="prewarm_analysis", schema_version=1, max_retries=1,
        error="ai_service_unavailable: fallback",
    )
    data = json.loads(build_v2_dead_retry_payload(source, task_type="prewarm_analysis"))
    assert data["max_retries"] == 3
    assert data["retry_count"] == 0
    assert data["generation"] == 7
    assert data["payload"] == {"value": 1}


def test_generic_retry_uses_registered_budget_policy_without_task_specific_branches(monkeypatch):
    source = dead_payload(max_retries=1)
    observed = []

    def budget_policy(task_data):
        observed.append(dict(task_data))
        return 4

    monkeypatch.setitem(worker_task_types._DEAD_RETRY_BUDGET_POLICIES, "demo", budget_policy)
    data = json.loads(build_v2_dead_retry_payload(source, task_type="demo", now=123.0))
    assert observed[0]["error"] == "fatal"
    assert data["max_retries"] == 4
    assert data["error"] == ""
    assert data["retry_count"] == 0
    assert data["generation"] == 7


def test_other_task_does_not_inherit_prewarm_recovery_from_error_text():
    source = dead_payload(max_retries=1, error="ai_service_unavailable: fallback")
    data = json.loads(build_v2_dead_retry_payload(source, task_type="demo"))
    assert data["max_retries"] == 1
