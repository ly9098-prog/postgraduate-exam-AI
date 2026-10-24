"""Project mixed learning-history rows into the stable public response."""

from __future__ import annotations

from typing import Any


def build_history_allocation_fallback(
    *,
    record_type: str,
    subject_id: int | None,
    subject_code: str,
    subject_name: str,
) -> list[dict[str, Any]]:
    """Preserve the pomodoro-only single-subject fallback."""
    if record_type != "pomodoro":
        return []
    return [
        {
            "subject_id": subject_id,
            "subject_code": subject_code,
            "subject_name": subject_name,
            "weight_basis_points": 10000,
        }
    ]


def build_history_item(
    *,
    row: Any,
    subject: Any,
    allocations: list[dict[str, Any]],
    equal_408_mode: str,
) -> dict[str, Any]:
    """Return one history item without changing source rows or allocations."""
    subject_id = row.subject_id
    subject_code = subject.code if subject is not None else ""
    subject_name = subject.name if subject is not None else "未分类"
    record_allocations = (
        allocations if row.record_type == "pomodoro" else []
    )
    if row.record_type == "pomodoro" and not record_allocations:
        record_allocations = build_history_allocation_fallback(
            record_type=row.record_type,
            subject_id=subject_id,
            subject_code=subject_code,
            subject_name=subject_name,
        )
    return {
        "record_key": f"{row.record_type}:{row.id}",
        "record_type": row.record_type,
        "id": row.id,
        "user_id": row.user_id,
        "subject_id": subject_id,
        "subject_code": subject_code,
        "subject_name": subject_name,
        "start_time": row.start_time,
        "end_time": row.end_time,
        "actual_duration": row.actual_duration,
        "status": row.status,
        "preset": row.preset,
        "allocation_mode": (
            equal_408_mode if len(record_allocations) > 1 else "single"
        )
        if row.record_type == "pomodoro"
        else None,
        "subject_allocations": record_allocations,
    }
