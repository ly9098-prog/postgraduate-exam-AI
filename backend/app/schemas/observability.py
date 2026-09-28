"""Typed response contracts for admin health and async-task diagnostics.

These models intentionally describe only fields exposed to the admin frontend.
Internal exception payloads and queue task bodies remain outside the OpenAPI
contract so generated frontend types cannot accidentally encourage leaking them.
"""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field

from app.schemas.base import BaseModel

HealthSeverity = Literal["ok", "warning", "error"]


class SystemHealthCheckItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    ok: bool
    severity: HealthSeverity
    code: str | None = None
    message: str


class SystemHealthResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ok: bool
    checks: dict[str, SystemHealthCheckItem]


class TaskHealthIssueResponse(BaseModel):
    code: str
    severity: Literal["warning", "error"]
    message: str
    value: int | float | None = None


class TaskHealthSummaryResponse(BaseModel):
    ok: bool
    severity: HealthSeverity
    issues: list[TaskHealthIssueResponse] = Field(default_factory=list)


class TaskQueueDiagnosticResponse(BaseModel):
    task_type: str
    ready: int = 0
    processing: int = 0
    retry: int = 0
    dead: int = 0
    corrupt: int = 0
    oldest_ready_seconds: int = 0


class TaskOutboxFailureResponse(BaseModel):
    outbox_id: int
    task_id: str
    task_type: str
    retry_count: int = 0
    last_error: str | None = None
    trace_id: str | None = None
    request_id: str | None = None
    updated_at: str


class TaskOutboxDiagnosticsResponse(BaseModel):
    counts: dict[str, int]
    unpublished: int
    oldest_unpublished_seconds: int
    oldest_unpublished_at: str | None = None
    pending_by_type: dict[str, int]
    recent_failures: list[TaskOutboxFailureResponse] = Field(default_factory=list)


class TaskQueueTotalsResponse(BaseModel):
    ready: int = 0
    processing: int = 0
    retry: int = 0
    dead: int = 0
    corrupt: int = 0


class TaskRedisMemoryResponse(BaseModel):
    used_bytes: int
    max_bytes: int
    used_percent: float | None = None
    evicted_keys: int = 0
    warning_percent: int = 50
    error_percent: int = 75


class TaskRedisDiagnosticsResponse(BaseModel):
    configured: bool
    available: bool
    error: str | None = None
    queues: list[TaskQueueDiagnosticResponse] = Field(default_factory=list)
    totals: TaskQueueTotalsResponse
    oldest_ready_seconds: int = 0
    memory: TaskRedisMemoryResponse | None = None


class TaskProjectionDiagnosticsResponse(BaseModel):
    unprojected: int
    oldest_age_sec: int
    oldest_answered_at: str | None = None
    projection_receipts_total: int
    repairs_scheduled_24h: int


class TaskTrendPointResponse(BaseModel):
    date: str
    created: int = 0
    published: int = 0
    failed: int = 0
    projection_receipts: int = 0


class TaskDiagnosticsResponse(BaseModel):
    generated_at: str
    async_runtime_expected: bool
    health: TaskHealthSummaryResponse
    outbox: TaskOutboxDiagnosticsResponse
    redis: TaskRedisDiagnosticsResponse
    projection: TaskProjectionDiagnosticsResponse
    trend: list[TaskTrendPointResponse] = Field(default_factory=list)


class TaskTraceQueueStateResponse(BaseModel):
    status: str | None = None
    retry_count: int = 0
    generation: int = 0
    created_at: float | None = None
    updated_at: float | None = None
    last_error: str | None = None


class TaskTraceItemResponse(BaseModel):
    outbox_id: int
    task_id: str
    task_type: str
    trace_id: str | None = None
    request_id: str | None = None
    outbox_status: str
    outbox_retry_count: int
    outbox_error: str | None = None
    created_at: str
    published_at: str | None = None
    updated_at: str
    practice_record_id: int | None = None
    projection_receipt_at: str | None = None
    queue: TaskTraceQueueStateResponse | None = None


class TaskTraceResponse(BaseModel):
    trace_id: str
    redis_available: bool
    items: list[TaskTraceItemResponse] = Field(default_factory=list)
    total: int
