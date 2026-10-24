"""Versioned in-memory contract for durable task queue tasks."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.services.practice.answer_projection_contract import (
    ANSWER_PROJECTION_MINIMUM_WORKER_VERSION,
    ANSWER_PROJECTION_TASK_SCHEMA_VERSION,
    ANSWER_PROJECTION_TASK_TYPE,
)

_DEFAULT_MAX_RETRIES = 3
_CURRENT_TASK_SCHEMA_VERSION = 2
_MINIMUM_WORKER_VERSION = 1


class TaskStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD = "dead"
    CORRUPT = "corrupt"
    CANCELLED = "cancelled"
    CANCEL_REQUESTED = "cancel_requested"


@dataclass
class EnqueueResult:
    """Result of an enqueue attempt."""

    accepted: bool = True
    task_id: str | None = None
    reason: str = ""
    retry_after: int = 0

    def __bool__(self) -> bool:
        return self.accepted


def _normalize_task_schema_version(task_type: str, schema_version: int) -> int:
    """Validate task schema versions; never silently upgrade incompatible work."""
    if task_type == ANSWER_PROJECTION_TASK_TYPE:
        if schema_version != ANSWER_PROJECTION_TASK_SCHEMA_VERSION:
            raise ValueError(
                "unsupported answer_projection schema_version="
                f"{schema_version}; required={ANSWER_PROJECTION_TASK_SCHEMA_VERSION}"
            )
        return ANSWER_PROJECTION_TASK_SCHEMA_VERSION
    return schema_version


def _minimum_worker_version_for_task(task_type: str, schema_version: int) -> int:
    """Return the oldest worker allowed to execute one task schema."""
    if (
        task_type == ANSWER_PROJECTION_TASK_TYPE
        and schema_version >= ANSWER_PROJECTION_TASK_SCHEMA_VERSION
    ):
        return ANSWER_PROJECTION_MINIMUM_WORKER_VERSION
    return _MINIMUM_WORKER_VERSION


@dataclass
class Task:
    """A task in the durable queue."""

    task_id: str
    task_type: str
    payload: dict[str, Any]
    status: TaskStatus = TaskStatus.PENDING
    retry_count: int = 0
    max_retries: int = _DEFAULT_MAX_RETRIES
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    lease_expires_at: float = 0.0
    owner_token: str = ""
    error: str = ""
    generation: int = 0
    schema_version: int = _CURRENT_TASK_SCHEMA_VERSION
    minimum_worker_version: int = _MINIMUM_WORKER_VERSION
    created_by_version: str = ""
    trace_id: str = ""
    request_id: str = ""

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "payload": self.payload,
            "status": self.status.value,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "lease_expires_at": self.lease_expires_at,
            "owner_token": self.owner_token,
            "error": self.error,
            "generation": self.generation,
            "schema_version": self.schema_version,
            "minimum_worker_version": self.minimum_worker_version,
            "created_by_version": self.created_by_version,
            "trace_id": self.trace_id,
            "request_id": self.request_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Task:
        return cls(
            task_id=d["task_id"],
            task_type=d["task_type"],
            payload=d.get("payload", {}),
            status=TaskStatus(d.get("status", "pending")),
            retry_count=d.get("retry_count", 0),
            max_retries=d.get("max_retries", _DEFAULT_MAX_RETRIES),
            created_at=d.get("created_at", 0.0),
            updated_at=d.get("updated_at", 0.0),
            lease_expires_at=d.get("lease_expires_at", 0.0),
            owner_token=d.get("owner_token", ""),
            error=d.get("error", ""),
            generation=d.get("generation", 0),
            schema_version=d.get("schema_version", 1),
            minimum_worker_version=d.get("minimum_worker_version", 1),
            created_by_version=d.get("created_by_version", ""),
            trace_id=d.get("trace_id", ""),
            request_id=d.get("request_id", ""),
        )
