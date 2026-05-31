from pydantic import BaseModel, Field


class WechatLogin(BaseModel):
    code: str


class UserResponse(BaseModel):
    id: int
    nickname: str | None = None
    avatar_url: str | None = None
    is_admin: bool = False
    role: str = "user"
    role_name: str = "user"
    permissions: list[str] = Field(default_factory=list)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class UserUpdate(BaseModel):
    nickname: str | None = None
    avatar_url: str | None = None
