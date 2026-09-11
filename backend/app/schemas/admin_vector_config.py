from app.schemas.base import BaseModel

"""pgvector / Embedding 运行配置 schemas。

Embedding 的 Provider / API Key / Base URL / Model ID 统一来自
``admin_ai_model_configs``。本配置只保存“选哪个 Embedding 模型”以及
向量检索运行参数，避免形成第二套模型凭据来源。
"""

from datetime import datetime

from pydantic import ConfigDict, Field


def _parse_optional_int(raw: str | None) -> int | None:
    if raw is None or not str(raw).strip():
        return None
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _configs_to_response(configs: dict[str, str]) -> "VectorConfigResponse":
    """从 ``admin_ai_configs`` 键值对构建向量运行配置。"""
    return VectorConfigResponse(
        vector_enabled=configs.get("vector_enabled", "false").lower() == "true",
        vector_cache_ttl_sec=int(configs.get("vector_cache_ttl_sec", 300)),
        vector_top_k=int(configs.get("vector_top_k", 100)),
        vector_similarity_threshold=float(
            configs.get("vector_similarity_threshold", "0.15")
        ),
        embedding_model_config_id=_parse_optional_int(
            configs.get("embedding_model_config_id")
        ),
        embedding_dim=int(configs.get("embedding_dim", 1024)),
        embedding_timeout=int(configs.get("embedding_timeout", 30)),
        embedding_batch_size=int(configs.get("embedding_batch_size", 16)),
    )


class VectorConfigResponse(BaseModel):
    """向量检索配置。

    模型凭据不在这里返回；前端通过 ``/ai-models`` 获取已注册模型，并按
    ``features`` 中的 ``embedding`` 能力筛选。
    """

    model_config = ConfigDict(from_attributes=True)

    # ── Vector Search ──
    vector_enabled: bool
    vector_cache_ttl_sec: int
    vector_top_k: int
    vector_similarity_threshold: float

    # ── Embedding runtime ──
    embedding_model_config_id: int | None = None
    embedding_dim: int
    embedding_timeout: int
    embedding_batch_size: int

    # ── Metadata ──
    updated_at: datetime | None = None


class VectorConfigPatchRequest(BaseModel):
    """部分更新向量配置。模型凭据必须在“模型配置”页面维护。"""

    # ── Vector Search ──
    vector_enabled: bool | None = None
    vector_cache_ttl_sec: int | None = Field(default=None, ge=0, le=86400)
    vector_top_k: int | None = Field(default=None, ge=1, le=10000)
    vector_similarity_threshold: float | None = Field(default=None, ge=0.0, le=1.0)

    # ── Embedding model selection / runtime ──
    embedding_model_config_id: int | None = Field(default=None, ge=1)
    embedding_dim: int | None = Field(default=None, ge=1, le=8192)
    embedding_timeout: int | None = Field(default=None, ge=1, le=300)
    embedding_batch_size: int | None = Field(default=None, ge=1, le=256)


class EmbeddingTestRequest(BaseModel):
    """测试当前/指定的已注册 Embedding 模型。"""

    model_config_id: int | None = Field(default=None, ge=1)
    dim: int | None = Field(default=None, ge=1, le=8192)
    timeout: int | None = Field(default=None, ge=1, le=300)


class EmbeddingTestResponse(BaseModel):
    """Embedding API 连通性测试结果。"""

    success: bool
    status: str  # ok | auth_error | network_error | timeout | dimension_mismatch | format_error
    message: str = ""
    latency_ms: int = 0
    returned_dim: int | None = None
