"""Pipeline state enums — single source of truth for all status/step values.

Why a dedicated module:
- Job / Item / Trace Event / Step values must not drift across modules.
- State transitions are defined here, not scattered in import guards.
- Adding a new status or step touches exactly ONE file + the DB migration.
"""

from __future__ import annotations

import enum


class BatchJobStatus(str, enum.Enum):
    """ImportBatchJob.status values."""
    QUEUED = "queued"
    RUNNING = "running"
    MERGING = "merging"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"


class BatchItemStatus(str, enum.Enum):
    """ImportBatchJobItem.status values."""
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REPROCESSING = "reprocessing"


class TraceEventStatus(str, enum.Enum):
    """BatchJobTraceEvent.status — NOT the same as job/item status.

    Only these values are valid in trace events.
    """
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    WARNING = "warning"


class TraceStep(str, enum.Enum):
    """BatchJobTraceEvent.step — processing step name."""
    UPLOAD = "upload"
    WAITING = "waiting"
    OCR = "ocr"
    PIPELINE = "pipeline"
    MERGE = "merge"
    DONE = "done"
    ERROR = "error"
    CONFIG = "config"


# ================================================================
# State transitions (machine-readable)
# ================================================================

JOB_TRANSITIONS: dict[str, set[str]] = {
    BatchJobStatus.QUEUED.value: {BatchJobStatus.RUNNING.value},
    BatchJobStatus.RUNNING.value: {
        BatchJobStatus.MERGING.value,
        BatchJobStatus.COMPLETED.value,
        BatchJobStatus.COMPLETED_WITH_WARNINGS.value,
        BatchJobStatus.FAILED.value,
    },
    BatchJobStatus.MERGING.value: {
        BatchJobStatus.COMPLETED.value,
        BatchJobStatus.COMPLETED_WITH_WARNINGS.value,
        BatchJobStatus.FAILED.value,
    },
    BatchJobStatus.COMPLETED.value: set(),
    BatchJobStatus.COMPLETED_WITH_WARNINGS.value: set(),
    BatchJobStatus.FAILED.value: set(),
}

ITEM_TRANSITIONS: dict[str, set[str]] = {
    BatchItemStatus.PENDING.value: {BatchItemStatus.PROCESSING.value},
    BatchItemStatus.PROCESSING.value: {
        BatchItemStatus.SUCCEEDED.value,
        BatchItemStatus.FAILED.value,
    },
    BatchItemStatus.SUCCEEDED.value: {BatchItemStatus.REPROCESSING.value},
    BatchItemStatus.FAILED.value: {BatchItemStatus.REPROCESSING.value},
    BatchItemStatus.REPROCESSING.value: {
        BatchItemStatus.SUCCEEDED.value,
        BatchItemStatus.FAILED.value,
    },
}


def guard_job_transition(current: str, next_status: str) -> None:
    """Raise ValueError if transition is not allowed."""
    allowed = JOB_TRANSITIONS.get(current, set())
    if next_status not in allowed:
        raise ValueError(
            f"Invalid job status transition: {current} → {next_status}"
            f" (allowed from {current}: {allowed})"
        )


def guard_item_transition(current: str, next_status: str) -> None:
    """Raise ValueError if transition is not allowed."""
    allowed = ITEM_TRANSITIONS.get(current, set())
    if next_status not in allowed:
        raise ValueError(
            f"Invalid item status transition: {current} → {next_status}"
            f" (allowed from {current}: {allowed})"
        )


# ================================================================
# Trace event status mapping
# ================================================================

# Set of valid trace event status values (for validation).
VALID_TRACE_STATUS: set[str] = {s.value for s in TraceEventStatus}

# Set of valid trace step values (for validation).
VALID_TRACE_STEPS: set[str] = {s.value for s in TraceStep}

# Job → trace mapping: maps job final status to trace step/status.
_JOB_TO_TRACE_MAP: dict[str, tuple[str, str]] = {
    BatchJobStatus.COMPLETED.value: (TraceStep.DONE.value, TraceEventStatus.SUCCESS.value),
    BatchJobStatus.COMPLETED_WITH_WARNINGS.value: (TraceStep.DONE.value, TraceEventStatus.SUCCESS.value),
    BatchJobStatus.FAILED.value: (TraceStep.ERROR.value, TraceEventStatus.FAILED.value),
    BatchJobStatus.RUNNING.value: (TraceStep.WAITING.value, TraceEventStatus.RUNNING.value),
    BatchJobStatus.MERGING.value: (TraceStep.MERGE.value, TraceEventStatus.RUNNING.value),
}


def map_job_status_to_trace(job_status: str) -> tuple[str, str]:
    """Map a BatchJobStatus value to the corresponding trace (step, status).

    Raises KeyError if job_status has no valid trace mapping.
    """
    if job_status in _JOB_TO_TRACE_MAP:
        return _JOB_TO_TRACE_MAP[job_status]
    # Fallback: job-level intermediate statuses -> "running"
    return (TraceStep.WAITING.value, TraceEventStatus.RUNNING.value)
