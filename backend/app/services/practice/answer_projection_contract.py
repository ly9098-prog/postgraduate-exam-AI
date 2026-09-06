"""Stable contract for asynchronous practice-answer projection.

``practice_records`` is a per-answer event table.  The batch-shaped columns from
its original design are retired permanently; batch/session aggregates live in
``practice_sessions``.  Keep the async task protocol versioned so a rolling
deployment cannot silently route a new per-answer projection task to a worker
that still assumes the retired batch schema.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ANSWER_PROJECTION_TASK_TYPE = "answer_projection"
ANSWER_PROJECTION_TASK_SCHEMA_VERSION = 2
ANSWER_PROJECTION_MINIMUM_WORKER_VERSION = 2

# These columns belonged to the pre-refactor batch-shaped PracticeRecord.  They
# must not be mapped by the ORM, queried by services, or present in the final DB
# schema.  ``mode`` is intentionally absent: it was retained with new per-answer
# semantics and is still consumed by behavior analytics.
RETIRED_PRACTICE_BATCH_COLUMNS = frozenset({
    "question_ids",
    "answers",
    "correct_count",
    "wrong_count",
    "duration_sec",
    "started_at",
    "finished_at",
})

# Minimal durable event contract required by answer projection.  Keeping this
# list explicit makes accidental schema drift visible at the worker boundary.
REQUIRED_PROJECTION_COLUMNS = frozenset({
    "id",
    "user_id",
    "question_id",
    "question_version_id",
    "subject_id",
    "question_type",
    "user_answer",
    "is_correct",
    "used_time",
    "answered_at",
    "created_at",
    "projection_state",
    "mode",
})


@dataclass(frozen=True, slots=True)
class AnswerProjectionTaskPayload:
    practice_record_id: int
    request_id: str | None


def parse_answer_projection_payload(payload: Any) -> AnswerProjectionTaskPayload:
    """Validate the small per-answer task payload.

    Projection tasks carry only an immutable PracticeRecord identity plus
    request correlation.  Retired batch fields are rejected explicitly so they
    cannot creep back into the queue contract through a future caller.
    """
    if not isinstance(payload, dict):
        raise ValueError("answer_projection payload must be an object")

    retired = sorted(RETIRED_PRACTICE_BATCH_COLUMNS.intersection(payload.keys()))
    if retired:
        raise ValueError(
            "answer_projection payload contains retired practice batch fields: "
            + ", ".join(retired)
        )

    try:
        practice_record_id = int(payload.get("practice_record_id") or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("answer_projection practice_record_id must be an integer") from exc
    if practice_record_id <= 0:
        raise ValueError("answer_projection practice_record_id must be positive")

    raw_request_id = payload.get("request_id")
    request_id = None
    if raw_request_id not in (None, ""):
        request_id = str(raw_request_id).strip() or None

    return AnswerProjectionTaskPayload(
        practice_record_id=practice_record_id,
        request_id=request_id,
    )
