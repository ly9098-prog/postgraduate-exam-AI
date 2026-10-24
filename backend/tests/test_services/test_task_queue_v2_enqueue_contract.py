"""Compatibility baseline for v2 enqueue request preparation."""

from __future__ import annotations

import json

import pytest

from app.services.task_queue_v2_enqueue_contract import (
    build_v2_enqueue_plan,
    v2_enqueue_duplicate,
    v2_enqueue_internal_error,
    v2_enqueue_queue_full,
    v2_enqueue_unavailable,
)


def correlation(payload):
    return payload.get("trace_id", ""), payload.get("request_id", "")


def test_plan_generates_task_id_and_serializes_task_payload():
    plan = build_v2_enqueue_plan(
        "demo",
        {"trace_id": "trace", "request_id": "request"},
        task_id=None,
        max_retries=3,
        schema_version=None,
        minimum_worker_version=None,
        correlation=correlation,
    )
    data = json.loads(plan.task_json)

    assert plan.idempotent is False
    assert plan.task.task_id.startswith("task_")
    assert data["task_type"] == "demo"
    assert data["schema_version"] == 2
    assert data["minimum_worker_version"] == 1
    assert data["trace_id"] == "trace"
    assert data["request_id"] == "request"


def test_explicit_task_id_selects_idempotent_enqueue_and_preserves_versions():
    plan = build_v2_enqueue_plan(
        "demo",
        {},
        task_id="task-1",
        max_retries=1,
        schema_version=1,
        minimum_worker_version=4,
        correlation=correlation,
    )

    assert plan.idempotent is True
    assert plan.task.task_id == "task-1"
    assert plan.task.max_retries == 1
    assert plan.task.schema_version == 1
    assert plan.task.minimum_worker_version == 4


def test_invalid_versions_are_rejected_before_redis_access():
    with pytest.raises(ValueError, match="schema_version must be positive"):
        build_v2_enqueue_plan(
            "demo",
            {},
            task_id=None,
            max_retries=1,
            schema_version=0,
            minimum_worker_version=None,
            correlation=correlation,
        )
    with pytest.raises(ValueError, match="minimum_worker_version must be positive"):
        build_v2_enqueue_plan(
            "demo",
            {},
            task_id=None,
            max_retries=1,
            schema_version=None,
            minimum_worker_version=0,
            correlation=correlation,
        )


def test_unavailable_result_preserves_historical_shape():
    result = v2_enqueue_unavailable()
    assert result.accepted is False
    assert result.task_id is None
    assert result.reason == "redis_unavailable"
    assert result.retry_after == 30


def test_lua_result_shapes_preserve_historical_contracts():
    duplicate = v2_enqueue_duplicate("task-1")
    assert duplicate.accepted is True
    assert duplicate.task_id == "task-1"
    assert duplicate.reason == "duplicate"

    queue_full = v2_enqueue_queue_full()
    assert queue_full.accepted is False
    assert queue_full.task_id is None
    assert queue_full.reason == "queue_full"
    assert queue_full.retry_after == 30

    internal_error = v2_enqueue_internal_error()
    assert internal_error.accepted is False
    assert internal_error.task_id is None
    assert internal_error.reason == "internal_error"
    assert internal_error.retry_after == 30
