from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AdminAIUsageMonthlyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    year_month: str
    call_count: int
    limit_snapshot: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AdminAISettingsResponse(BaseModel):
    id: int
    ai_parse_enabled: bool
    monthly_call_limit: int
    current_usage: AdminAIUsageMonthlyResponse
    remaining_calls: int | None
    updated_by: int | None = None
    updated_at: datetime | None = None


class AdminAISettingsPatchRequest(BaseModel):
    ai_parse_enabled: bool | None = None
    monthly_call_limit: int | None = Field(default=None, ge=0)
