"""Validate and rebuild dead v2 tasks for an administrator retry."""

from __future__ import annotations

import json
import time
from typing import Any

from app.services.practice.answer_projection_contract import (
    ANSWER_PROJECTION_TASK_TYPE,
    parse_answer_projection_payload,
)
from app.services.task_queue_contract import (
    TaskStatus,
    _minimum_worker_version_for_task,
    _normalize_task_schema_version,
)


class V2DeadRetryPayloadError(ValueError):
    """Raised for a dead payload that cannot safely re-enter the ready queue."""


def parse_v2_dead_retry_payload(
    raw_payload: Any,
    *,
    task_id: str,
    task_type: str,
) -> dict:
    """Parse and validate a dead task payload without changing Redis state."""
    try:
        task_data = json.loads(raw_payload)
    except (TypeError, json.JSONDecodeError) as exc:
        raise V2DeadRetryPayloadError("corrupt_payload") from exc
    if not isinstance(task_data, dict):
        raise V2DeadRetryPayloadError("payload_not_object")
    if (
        task_data.get("task_id") != task_id
        or task_data.get("task_type") != task_type
    ):
        raise V2DeadRetryPayloadError("identity_mismatch")
    return task_data


def build_v2_dead_retry_payload(
    task_data: dict,
    *,
    task_type: str,
    now: float | None = None,
) -> str:
    """Reset one retry cycle while preserving schema and fencing generation."""
    resolved_now = time.time() if now is None else now
    raw_schema_version = int(task_data.get("schema_version", 1) or 1)
    schema_version = _normalize_task_schema_version(task_type, raw_schema_version)
    if task_type == ANSWER_PROJECTION_TASK_TYPE:
        parse_answer_projection_payload(task_data.get("payload"))
    required_worker = _minimum_worker_version_for_task(task_type, schema_version)
    task_data.update(
        {
            "status": TaskStatus.PENDING.value,
            "retry_count": 0,
            "error": "",
            "updated_at": resolved_now,
            "lease_expires_at": 0.0,
            "owner_token": "",
            # Re-evaluate the worker floor for a fresh retry cycle. The schema
            # itself was validated above and is never auto-upgraded.
            "schema_version": schema_version,
            "minimum_worker_version": max(
                int(task_data.get("minimum_worker_version", 1) or 1),
                required_worker,
            ),
        }
    )
    return json.dumps(task_data, default=str)
