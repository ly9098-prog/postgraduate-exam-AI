from datetime import date, datetime
from typing import Literal

from pydantic import Field

from app.schemas.base import BaseModel

StudyPlanPriority = Literal["balanced", "review", "weakness", "new", "exam"]
StudyPlanCategory = Literal["review", "weakness", "new", "exam"]
StudyPlanRoute = Literal["review_today", "practice", "exam_list"]
StudyPlanPhase = Literal["foundation", "steady", "sprint", "target_day"]


class StudyPlanUpsertRequest(BaseModel):
    target_date: date
    daily_minutes: int = Field(default=90, ge=15, le=720)
    weekly_days: int = Field(default=6, ge=1, le=7)
    priority_mode: StudyPlanPriority = "balanced"


class StudyPlanConfigResponse(BaseModel):
    id: int
    target_date: date
    daily_minutes: int
    weekly_days: int
    priority_mode: StudyPlanPriority
    revision: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class StudyPlanSuggestedDefaults(BaseModel):
    daily_minutes: int = 90
    weekly_days: int = 6
    priority_mode: StudyPlanPriority = "balanced"


class StudyPlanCountdown(BaseModel):
    target_date: date
    days_remaining: int
    phase: StudyPlanPhase
    phase_label: str


class StudyPlanWeeklyProgress(BaseModel):
    week_start: date
    week_end: date
    target_days: int
    active_days: int
    remaining_days: int
    target_met: bool


class StudyPlanTaskAllocation(BaseModel):
    category: StudyPlanCategory
    title: str
    reason: str
    planned_minutes: int = 0
    completed_minutes: int = 0
    remaining_minutes: int = 0
    adjusted_minutes: int = 0
    status: Literal["done", "available", "unavailable"] = "available"
    action_label: str = ""
    route: StudyPlanRoute | None = None
    route_params: dict = Field(default_factory=dict)
    estimated_question_count: int = 0


class StudyPlanToday(BaseModel):
    date: date
    target_minutes: int
    completed_minutes: int
    remaining_minutes: int
    focus_minutes: int
    is_rest_day: bool = False
    completion_percent: int = 0
    primary_category: StudyPlanCategory | None = None
    allocations: list[StudyPlanTaskAllocation] = Field(default_factory=list)


class StudyPlanOverviewResponse(BaseModel):
    configured: bool
    date: date
    plan: StudyPlanConfigResponse | None = None
    countdown: StudyPlanCountdown | None = None
    weekly: StudyPlanWeeklyProgress | None = None
    today: StudyPlanToday | None = None
    suggested_defaults: StudyPlanSuggestedDefaults = Field(
        default_factory=StudyPlanSuggestedDefaults
    )
