from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AdminLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class AdminChangePasswordRequest(BaseModel):
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


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


class AdminLoginResponse(BaseModel):
    """Login/2FA-verify response. When two_factor_required, tokens are absent."""

    access_token: str | None = None
    token_type: str = "bearer"
    user: AdminUserResponse | None = None
    role: AdminRoleResponse | None = None
    permissions: list[str] = []
    two_factor_required: bool = False
    pending_token: str | None = None


class TwoFactorVerifyRequest(BaseModel):
    pending_token: str = Field(min_length=1)
    code: str = Field(min_length=6, max_length=16)


class TwoFactorConfirmRequest(BaseModel):
    code: str = Field(min_length=6, max_length=16)


class TwoFactorDisableRequest(BaseModel):
    code: str = Field(min_length=6, max_length=16)


class TwoFactorSetupResponse(BaseModel):
    secret: str
    otpauth_uri: str
    issuer: str
    username: str
    already_enabled: bool = False


class TwoFactorConfirmResponse(BaseModel):
    backup_codes: list[str]


class AdminMeResponse(BaseModel):
    user: AdminUserResponse
    role: AdminRoleResponse
    permissions: list[str]
    two_factor_enabled: bool = False
