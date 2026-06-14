from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

VALID_SUBJECTS = {
    "data_structure", "computer_organization", "operating_system",
    "computer_network", "english", "math", "politics",
}


class PomodoroStartRequest(BaseModel):
    subject: str = ""
    chapter_id: str | None = None
    preset: Literal["standard", "long", "custom", "debug"] = "standard"
    work_duration: int = Field(default=25, ge=0, le=120)
    break_duration: int = Field(default=5, ge=0, le=120)
    notification_enabled: bool = False

    @field_validator("subject")
    @classmethod
    def validate_subject(cls, v: str) -> str:
        if v and v not in VALID_SUBJECTS:
            raise ValueError(f"无效的科目: {v}")
        return v


class PomodoroCompleteRequest(BaseModel):
    total_paused_ms: int = Field(default=0, ge=0)
    actual_duration_sec: int | None = Field(default=None, ge=0, description="If provided, used directly instead of computing from timestamps")


class PomodoroSessionResponse(BaseModel):
    id: int
    user_id: int
    subject: str
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
    created_at: datetime

    model_config = {"from_attributes": True}


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
    subject: str
    sessions: int = 0
    duration_sec: int = 0


class PomodoroHistoryResponse(BaseModel):
    items: list[PomodoroSessionResponse]
    total: int
    page: int
    page_size: int
