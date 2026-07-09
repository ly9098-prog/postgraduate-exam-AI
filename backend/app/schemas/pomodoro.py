from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class PomodoroStartRequest(BaseModel):
    subject_id: int
    chapter_id: str | None = None
    preset: Literal["standard", "long", "custom", "debug", "free"] = "standard"
    work_duration: int = Field(default=25, ge=0, le=120)
    break_duration: int = Field(default=5, ge=0, le=120)
    notification_enabled: bool = False


class PomodoroCompleteRequest(BaseModel):
    total_paused_ms: int = Field(default=0, ge=0)
    actual_duration_sec: int | None = Field(default=None, ge=0, description="If provided, used directly instead of computing from timestamps")


class PomodoroSessionResponse(BaseModel):
    id: int
    user_id: int
    subject_id: int | None = None
    subject_code: str = ""
    subject_name: str = ""
    chapter_id: str | None = None
    preset: str
    work_duration: int
    break_duration: int
    start_time: datetime
    end_time: datetime | None = None
    expected_end_time: datetime | None = None
    actual_duration: int | None = None
    status: str
    notification_enabled: bool = False
    notification_sent: bool = False
    notification_sent_at: datetime | None = None
    paused_at: datetime | None = None
    total_paused_sec: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_with_subject(cls, session) -> "PomodoroSessionResponse":
        d = {
            "id": session.id,
            "user_id": session.user_id,
            "subject_id": session.subject_id,
            "chapter_id": session.chapter_id,
            "preset": session.preset,
            "work_duration": session.work_duration,
            "break_duration": session.break_duration,
            "start_time": session.start_time,
            "end_time": session.end_time,
            "expected_end_time": session.expected_end_time,
            "actual_duration": session.actual_duration,
            "status": session.status,
            "notification_enabled": session.notification_enabled,
            "notification_sent": session.notification_sent,
            "notification_sent_at": session.notification_sent_at,
            "paused_at": session.paused_at,
            "total_paused_sec": session.total_paused_sec or 0,
            "created_at": session.created_at,
        }
        if session.subject_ref:
            d["subject_code"] = session.subject_ref.code or ""
            d["subject_name"] = session.subject_ref.name or ""
        else:
            d["subject_code"] = ""
            d["subject_name"] = "未分类"
        return cls(**d)


class PomodoroStatsResponse(BaseModel):
    today_sessions: int = 0
    today_duration_sec: int = 0
    week_sessions: int = 0
    week_duration_sec: int = 0


class PomodoroTrendPoint(BaseModel):
    date: str
    sessions: int = 0
    duration_sec: int = 0


class PomodoroSubjectBreakdown(BaseModel):
    subject_id: int | None = None
    subject_code: str = ""
    subject_name: str = ""
    sessions: int = 0
    duration_sec: int = 0


class PomodoroHistoryResponse(BaseModel):
    items: list[PomodoroSessionResponse]
    total: int
    page: int
    page_size: int
