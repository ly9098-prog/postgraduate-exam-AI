"""Prepare v2 failure payloads without owning Redis state transitions."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

from app.services.task_queue_contract import Task, TaskStatus


@dataclass(slots=True)
class V2FailIdentity:
    task_id: str
    task_type: str
    owner_token: str


@dataclass(slots=True)
class V2RetryPlan:
    retry_count: int
    max_retries: int
    delay: float
    task_json: str
    updated_at: float


@dataclass(slots=True)
class V2DeadPlan:
    task_json: str
    retry_count: int
    updated_at: float


def resolve_v2_fail_identity(
    task_or_id: Task | str,
    *,
    task_type: str | None = None,
) -> V2FailIdentity:
    """Return the fenced identity, including empty fields for invalid input."""
    if isinstance(task_or_id, Task):
        return V2FailIdentity(
            task_or_id.task_id,
            task_or_id.task_type,
            task_or_id.owner_token,
        )
    task_id = task_or_id
    return V2FailIdentity(task_id, task_type or "", "")


def build_v2_retry_plan(task: Task, error: str, base_delay: float) -> V2RetryPlan:
    """Build the retry payload and exponential delay for the next attempt."""
    retry_count = task.retry_count + 1
    updated_at = time.time()
    data = task.to_dict()
    data.update(
        {
            "status": TaskStatus.FAILED.value,
            "retry_count": retry_count,
            "error": error,
            "updated_at": updated_at,
            "lease_expires_at": 0.0,
            "owner_token": "",
        }
    )
    return V2RetryPlan(
        retry_count=retry_count,
        max_retries=task.max_retries,
        delay=base_delay * (2 ** (retry_count - 1)),
        task_json=json.dumps(data, default=str),
        updated_at=updated_at,
    )


def build_v2_dead_plan(
    task_or_id: Task | str,
    error: str,
    *,
    retry_count: int,
    task_type: str = "",
    updated_at: float | None = None,
) -> V2DeadPlan:
    """Build the dead-letter payload while preserving the historical shape."""
    resolved_updated_at = time.time() if updated_at is None else updated_at
    if isinstance(task_or_id, Task):
        data = task_or_id.to_dict()
        data.update(
            {
                "status": TaskStatus.DEAD.value,
                "retry_count": retry_count,
                "error": error,
                "lease_expires_at": 0.0,
                "owner_token": "",
                "updated_at": resolved_updated_at,
            }
        )
    else:
        data = {
            "task_id": task_or_id,
            "task_type": task_type,
            "payload": {},
            "status": "dead",
        }
    return V2DeadPlan(
        task_json=json.dumps(data, default=str),
        retry_count=retry_count,
        updated_at=resolved_updated_at,
    )


def apply_v2_retry_result(task: Task, plan: V2RetryPlan, error: str) -> None:
    """Apply the accepted retry/dead outcome to the in-memory task snapshot."""
    task.retry_count = plan.retry_count
    task.error = error
    task.updated_at = plan.updated_at
    task.status = TaskStatus.FAILED
    task.lease_expires_at = 0.0


def apply_v2_dead_result(task_or_id: Task | str, plan: V2DeadPlan, error: str) -> None:
    """Apply the accepted dead outcome to the in-memory task snapshot."""
    if isinstance(task_or_id, Task):
        task_or_id.retry_count = plan.retry_count
        task_or_id.error = error
        task_or_id.updated_at = plan.updated_at
        task_or_id.status = TaskStatus.DEAD
        task_or_id.lease_expires_at = 0.0


def v2_fail_transition(result: int, retry_count: int, max_retries: int) -> str | None:
    """Map a Redis result to the historical task-state transition."""
    if result == 1:
        return "retry" if retry_count < max_retries else "dead"
    if result == 2:
        return "dead"
    return None
