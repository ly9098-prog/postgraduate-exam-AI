"""Export status transition rules shared by the service and scheduler processor."""

from __future__ import annotations

from app.schemas.export_task import ExportTaskStatus

_VALID_TRANSITIONS: dict[str, set[str]] = {
    ExportTaskStatus.PENDING: {ExportTaskStatus.PROCESSING},
    ExportTaskStatus.PROCESSING: {ExportTaskStatus.COMPLETED, ExportTaskStatus.FAILED},
    ExportTaskStatus.COMPLETED: {ExportTaskStatus.EXPIRED, ExportTaskStatus.PENDING},
    ExportTaskStatus.FAILED: {ExportTaskStatus.PENDING, ExportTaskStatus.EXPIRED},
    ExportTaskStatus.EXPIRED: {ExportTaskStatus.PENDING},
}


def validate_transition(
    current: str,
    target: str,
    task_id: int = 0,
) -> None:
    """Validate an export status transition.

    Raises ``ValueError`` if the transition is not allowed.
    """
    allowed = _VALID_TRANSITIONS.get(current)
    if allowed is None:
        raise ValueError(
            f"export_state_invalid: unknown current state '{current}' for task {task_id}"
        )
    if target not in allowed:
        raise ValueError(
            f"export_state_invalid: transition {current}→{target} "
            f"not allowed for task {task_id}"
        )
