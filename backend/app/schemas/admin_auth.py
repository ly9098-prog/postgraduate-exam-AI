from app.schemas.base import BaseModel
from datetime import datetime

from pydantic import ConfigDict, Field


class AdminLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class AdminChangePasswordRequest(BaseModel):
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


class AdminRoleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    display_name: str
    description: str | None = None
    is_system: bool


class AdminUserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str | None = None
    email: str | None = None
    is_active: bool
    role_id: int
    last_login_at: datetime | None = None
    last_login_ip: str | None = None


class AdminTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: AdminUserResponse
    role: AdminRoleResponse
    permissions: list[str] = []


class AdminMeResponse(BaseModel):
    user: AdminUserResponse
    role: AdminRoleResponse
    permissions: list[str]
