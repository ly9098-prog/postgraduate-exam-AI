from pydantic import BaseModel


class WechatLogin(BaseModel):
    code: str


class UserResponse(BaseModel):
    id: int
    nickname: str | None = None
    avatar_url: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class UserUpdate(BaseModel):
    nickname: str | None = None
    avatar_url: str | None = None
