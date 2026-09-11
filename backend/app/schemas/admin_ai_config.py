from app.schemas.base import BaseModel
from datetime import datetime

from pydantic import ConfigDict, Field, SecretStr

from app.core.secret_crypto import is_mask_placeholder


class AdminAiModelConfigResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    display_name: str
    provider: str
    api_base_url: str | None = None
    api_configured: bool = False
    api_key_masked: str | None = None
    is_enabled: bool
    is_default: bool
    sort_order: int
    feature: str | None = None
    features: list[str] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AdminAiModelConfigPatchRequest(BaseModel):
    name: str | None = None
    display_name: str | None = None
    provider: str | None = None
    is_enabled: bool | None = None
    is_default: bool | None = None
    api_key: SecretStr | None = None
    api_base_url: str | None = None
    feature: str | None = None
    features: list[str] | None = None

    def get_api_key_value(self) -> str | None:
        """Return the plaintext API key, or None if not provided / is mask placeholder."""
        if self.api_key is None:
            return None
        val = self.api_key.get_secret_value()
        if not val or is_mask_placeholder(val):
            return None
        return val


class AdminAiModelConfigCreateRequest(BaseModel):
    name: str
    display_name: str
    provider: str
    api_base_url: str
    api_key: SecretStr | None = None
    feature: str | None = None
    features: list[str] | None = None

    def get_api_key_value(self) -> str | None:
        """Return the plaintext API key, or None if not provided / is mask placeholder."""
        if self.api_key is None:
            return None
        val = self.api_key.get_secret_value()
        if not val or is_mask_placeholder(val):
            return None
        return val


class AdminAiConfigsResponse(BaseModel):
    """扁平映射: config_key → config_value (自动 JSON 反序列化)"""

    configs: dict


class AdminAiConfigsPatchRequest(BaseModel):
    """只提交要修改的配置项。不存在的 key 静默忽略。"""

    configs: dict = Field(default_factory=dict)


class ModelTestConnectionRequest(BaseModel):
    api_base_url: str
    api_key: SecretStr | None = None
    model_name: str
    model_id: int | None = None
    provider: str | None = None
    feature: str | None = None
    features: list[str] | None = None

    def get_api_key_value(self) -> str | None:
        """Return the plaintext API key, or None if not provided / is mask."""
        if self.api_key is None:
            return None
        val = self.api_key.get_secret_value()
        if not val or is_mask_placeholder(val):
            return None
        return val


class ModelTestConnectionResponse(BaseModel):
    success: bool
    status: str  # "ok" | "auth_error" | "model_not_found" | "network_error" | "timeout" | "format_error" | "unknown_error"
    message: str
    latency_ms: int | None = None
    model_returned: str | None = None
