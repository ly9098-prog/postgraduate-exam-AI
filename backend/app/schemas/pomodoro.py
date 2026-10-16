from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.base import BaseModel


class PomodoroStartRequest(BaseModel):
    subject_id: int
    allocation_mode: Literal["single", "equal_408_core_v1"] = "single"
    chapter_id: str | None = None
    preset: Literal["standard", "long", "custom", "debug", "free"] = "standard"
    work_duration: int = Field(default=25, ge=0, le=120)
    break_duration: int = Field(default=5, ge=0, le=120)
    notification_enabled: bool = False
    client_start_id: str | None = Field(
        default=None,
        min_length=8,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,63}$",
    )


class PomodoroActionRequest(BaseModel):
    """Optional client event time used only to reconstruct delayed offline actions.

    Duration remains server-authoritative: the service clamps this timestamp to the
    session timeline and current server time before using it. Older clients can keep
    sending an empty body.
    """

    client_action_at: datetime | None = None


class PomodoroCompleteRequest(PomodoroActionRequest):
    pass


class PomodoroResumeRequest(PomodoroActionRequest):
    pass


class PomodoroPauseRequest(PomodoroActionRequest):
    pass


class PomodoroSubjectAllocationResponse(BaseModel):
    subject_id: int | None = None
    subject_code: str
    subject_name: str
    weight_basis_points: int


class PomodoroSessionResponse(BaseModel):
    id: int
    user_id: int
    subject_id: int | None = None
    subject_code: str = ""
    subject_name: str = ""
    allocation_mode: Literal["single", "equal_408_core_v1"] = "single"
    subject_allocations: list["PomodoroSubjectAllocationResponse"] = []
    chapter_id: str | None = None
    client_start_id: str | None = None
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
    server_now: datetime | None = None

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_with_subject(cls, session) -> "PomodoroSessionResponse":
        d = {
            "id": session.id,
            "user_id": session.user_id,
            "subject_id": session.subject_id,
            "allocation_mode": (
                "equal_408_core_v1"
                if len(getattr(session, "subject_allocations", []) or []) > 1
                else "single"
            ),
            "subject_allocations": [
                {
                    "subject_id": item.subject_id,
                    "subject_code": item.subject_code_snapshot,
                    "subject_name": item.subject_name_snapshot,
                    "weight_basis_points": item.weight_basis_points,
                }
                for item in (getattr(session, "subject_allocations", []) or [])
            ],
            "chapter_id": session.chapter_id,
            "client_start_id": session.client_start_id,
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
            "server_now": datetime.utcnow(),
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
    today_date: str = ""
    week_start_date: str = ""
    day_start_minute: int = 0
    day_start_time: str = "00:00"


class PomodoroSettingsUpdate(BaseModel):
    day_start_minute: int = Field(ge=0, le=1439)


class PomodoroSettingsResponse(BaseModel):
    day_start_minute: int
    day_start_time: str
    timezone: str


class PomodoroDailySummarySubject(BaseModel):
    subject_id: int | None = None
    subject_code: str = ""
    subject_name: str = ""
    sessions: int = 0
    participation_sessions: int = 0
    duration_sec: int = 0


class PomodoroDailySummaryResponse(BaseModel):
    date: str
    timezone: str
    day_start_minute: int
    day_start_time: str
    sessions: int = 0
    duration_sec: int = 0
    subjects: list[PomodoroDailySummarySubject] = []


class PomodoroRangeSummaryResponse(BaseModel):
    """Learning-duration distribution for an inclusive study-day range."""

    start_date: str
    end_date: str
    timezone: str
    day_start_minute: int
    day_start_time: str
    sessions: int = 0
    duration_sec: int = 0
    active_days: int = 0
    subjects: list[PomodoroDailySummarySubject] = []


class PomodoroLifetimeSummaryResponse(BaseModel):
    """Compact lifetime roll-up used by the statistics overview header."""

    start_date: str
    end_date: str
    sessions: int = 0
    duration_sec: int = 0
    active_days: int = 0


class PomodoroTrendPoint(BaseModel):
    date: str
    sessions: int = 0
    duration_sec: int = 0


class PomodoroStatisticsOverviewResponse(BaseModel):
    """One-page payload for the mini-program statistics page.

    stats / trends / daily_summary share one bounded attribution pass; the compact
    lifetime_summary reuses the same attribution rules over the user's completed
    learning history.
    """

    stats: PomodoroStatsResponse
    trends: list[PomodoroTrendPoint]
    daily_summary: PomodoroDailySummaryResponse
    lifetime_summary: PomodoroLifetimeSummaryResponse


class LearningHistoryItem(BaseModel):
    """统计页统一学习记录 — 番茄钟与刷题会话混排。

    ``record_key`` 跨来源唯一（``pomodoro:<id>`` / ``practice:<id>`` /
    ``review:<id>``），供前端 WXML ``wx:key`` 使用，避免多张表 id 相同产生 key 冲突。
    """

    record_key: str
    record_type: Literal["pomodoro", "practice", "review"]
    id: int
    user_id: int
    subject_id: int | None = None
    subject_code: str = ""
    subject_name: str = ""
    start_time: datetime
    end_time: datetime | None = None
    actual_duration: int | None = None
    status: str
    preset: str | None = None
    allocation_mode: Literal["single", "equal_408_core_v1"] | None = None
    subject_allocations: list[PomodoroSubjectAllocationResponse] = []


class PomodoroHistoryResponse(BaseModel):
    items: list[LearningHistoryItem]
    total: int
    page: int
    page_size: int
