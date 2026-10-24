"""Prepare and interpret v2 enqueue requests without Redis ownership."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from app.services.practice.answer_projection_contract import (
    ANSWER_PROJECTION_TASK_TYPE,
    parse_answer_projection_payload,
)
from app.services.task_queue_contract import (
    _CURRENT_TASK_SCHEMA_VERSION,
    _minimum_worker_version_for_task,
    _normalize_task_schema_version,
    EnqueueResult,
    Task,
)


@dataclass(slots=True)
class V2EnqueuePlan:
    task: Task
    task_json: str
    idempotent: bool


def build_v2_enqueue_plan(
    task_type: str,
    payload: dict[str, Any],
    *,
    task_id: str | None,
    max_retries: int,
    schema_version: int | None,
    minimum_worker_version: int | None,
    correlation: Callable[[dict[str, Any]], tuple[str, str]],
) -> V2EnqueuePlan:
    """Validate producer inputs and build the immutable v2 task payload."""
    tid = task_id or f"task_{uuid.uuid4().hex}"
    trace_id, request_id = correlation(payload)
    effective_schema_version = int(
        _CURRENT_TASK_SCHEMA_VERSION if schema_version is None else schema_version
    )
    if effective_schema_version <= 0:
        raise ValueError("schema_version must be positive")
    effective_schema_version = _normalize_task_schema_version(
        task_type, effective_schema_version
    )
    if task_type == ANSWER_PROJECTION_TASK_TYPE:
        parse_answer_projection_payload(payload)
    effective_minimum_worker_version = int(
        _minimum_worker_version_for_task(task_type, effective_schema_version)
        if minimum_worker_version is None
        else minimum_worker_version
    )
    if effective_minimum_worker_version <= 0:
        raise ValueError("minimum_worker_version must be positive")
    task = Task(
        task_id=tid,
        task_type=task_type,
        payload=payload,
        max_retries=max_retries,
        trace_id=trace_id,
        request_id=request_id,
        schema_version=effective_schema_version,
        minimum_worker_version=effective_minimum_worker_version,
    )
    return V2EnqueuePlan(
        task=task,
        task_json=json.dumps(task.to_dict(), default=str),
        idempotent=task_id is not None,
    )


def v2_enqueue_unavailable() -> EnqueueResult:
    return EnqueueResult(
        accepted=False,
        task_id=None,
        reason="redis_unavailable",
        retry_after=30,
    )


def v2_enqueue_duplicate(task_id: str) -> EnqueueResult:
    return EnqueueResult(accepted=True, task_id=task_id, reason="duplicate")


def v2_enqueue_queue_full() -> EnqueueResult:
    return EnqueueResult(
        accepted=False,
        task_id=None,
        reason="queue_full",
        retry_after=30,
    )


def v2_enqueue_internal_error() -> EnqueueResult:
    return EnqueueResult(
        accepted=False,
        task_id=None,
        reason="internal_error",
        retry_after=30,
    )
