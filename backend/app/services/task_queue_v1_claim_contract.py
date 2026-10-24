"""Materialize v1 claimed tasks without owning Redis state transitions."""

from __future__ import annotations

import json
import time
from typing import Any

from app.services.task_queue_contract import Task, TaskStatus


def build_v1_claimed_task(
    result: Any,
    *,
    owner_token: str,
    lease_expiry: float,
    generation: int,
    now: float | None = None,
) -> Task | None:
    """Build a processing task from a ready-queue claim result."""
    if result is None:
        return None
    raw_payload, stored_token, stored_gen = result
    task = Task.from_dict(json.loads(raw_payload))
    task.status = TaskStatus.PROCESSING
    task.lease_expires_at = lease_expiry
    task.owner_token = stored_token or owner_token
    task.generation = int(stored_gen or generation)
    task.updated_at = time.time() if now is None else now
    return task


def build_v1_retry_claimed_task(
    retry_data: Any,
    *,
    owner_token: str,
    generation: int,
    lease_sec: int,
    now: float | None = None,
) -> Task | None:
    """Build a processing task from a retry-ZSET claim result."""
    if retry_data is None:
        return None
    resolved_now = time.time() if now is None else now
    raw_payload, _task_id, retry_token, retry_generation = retry_data
    task = Task.from_dict(json.loads(raw_payload))
    task.status = TaskStatus.PROCESSING
    task.lease_expires_at = resolved_now + lease_sec
    task.owner_token = retry_token or owner_token
    task.generation = int(retry_generation or generation)
    task.updated_at = resolved_now
    return task
