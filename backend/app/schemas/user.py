from pydantic import Field, field_validator

from app.schemas.base import BaseModel


class WechatLogin(BaseModel):
    code: str = Field(min_length=1, max_length=256)


class UserResponse(BaseModel):
    id: int
    nickname: str | None = None
    avatar_url: str | None = None
    profile_completed: bool = False
    is_admin: bool = False
    role: str = "user"
    role_name: str = "user"
    permissions: list[str] = Field(default_factory=list)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: int  # Unix timestamp
    refresh_token: str
    user: UserResponse


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=32, max_length=512)


class UserUpdate(BaseModel):
    nickname: str | None = Field(default=None, max_length=64)

    @field_validator("nickname")
    @classmethod
    def normalize_nickname(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.strip().split())
        if not normalized:
            raise ValueError("昵称不能为空")
        return normalized


class DeletionResponse(BaseModel):
    message: str
    deleted_at: int  # Unix timestamp
