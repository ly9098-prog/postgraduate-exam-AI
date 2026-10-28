from dataclasses import dataclass


@dataclass(frozen=True)
class PomodoroStartRequest:
    """The idempotency-relevant fields of a Pomodoro start request."""

    subject_id: int
    chapter_id: str | None
    preset: str
    work_duration: int
    break_duration: int
    notification_enabled: bool
