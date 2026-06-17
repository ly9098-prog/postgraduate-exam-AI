from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


FEATURE_VALUES = {"ocr", "completion", "analysis"}


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
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AdminAiModelConfigPatchRequest(BaseModel):
    name: str | None = None
    is_enabled: bool | None = None
    is_default: bool | None = None
    api_key: str | None = None
    api_base_url: str | None = None
    feature: str | None = None


class AdminAiModelConfigCreateRequest(BaseModel):
    name: str
    display_name: str
    provider: str
    api_base_url: str | None = None
    api_key: str | None = None
    feature: str | None = None


class AdminAiConfigsResponse(BaseModel):
    """扁平映射: config_key → config_value (自动 JSON 反序列化)"""
    configs: dict


class AdminAiConfigsPatchRequest(BaseModel):
    """只提交要修改的配置项。不存在的 key 静默忽略。"""
    configs: dict = Field(default_factory=dict)


class ModelTestConnectionRequest(BaseModel):
    api_base_url: str
    api_key: str
    model_name: str
    model_id: int | None = None


class ModelTestConnectionResponse(BaseModel):
    success: bool
    status: str  # "ok" | "auth_error" | "model_not_found" | "network_error" | "timeout" | "format_error" | "unknown_error"
    message: str
    latency_ms: int | None = None
    model_returned: str | None = None
