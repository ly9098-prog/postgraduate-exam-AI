from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AdminAppUserListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    openid: str
    nickname: str | None = None
    avatar_url: str | None = None
    is_banned: bool
    banned_reason: str | None = None
    banned_at: datetime | None = None
    banned_by: int | None = None
    created_at: datetime
    updated_at: datetime


class AdminAppUserDetail(AdminAppUserListItem):
    practice_count: int
    wrong_count: int
    recent_active_at: datetime | None = None


class AdminAppUserUpdateRequest(BaseModel):
    nickname: str | None = Field(default=None, max_length=64)


class AdminAppUserBindAdminRequest(BaseModel):
    admin_user_id: int


class AdminAppUserBindAdminResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    admin_user_id: int
    created_by: int | None = None
    created_at: datetime


class AdminAppUserBanRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=256)
