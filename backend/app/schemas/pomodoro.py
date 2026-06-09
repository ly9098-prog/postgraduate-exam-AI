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
    preset: Literal["standard", "long", "custom"] = "standard"
    work_duration: int = Field(default=25, ge=5, le=120)
    break_duration: int = Field(default=5, ge=5, le=120)

    @field_validator("subject")
    @classmethod
    def validate_subject(cls, v: str) -> str:
        if v and v not in VALID_SUBJECTS:
            raise ValueError(f"无效的科目: {v}")
        return v


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
    actual_duration: int | None = None
    status: str
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
