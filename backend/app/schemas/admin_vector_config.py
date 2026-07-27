"""pgvector / Embedding 配置的 Pydantic schemas。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.core.secret_crypto import is_mask_placeholder


class VectorConfigResponse(BaseModel):
    """返回给前端的完整向量配置。API key 以掩码形式返回，不暴露明文。"""

    model_config = ConfigDict(from_attributes=True)

    # ── Vector Search ──
    vector_enabled: bool
    vector_mode: str
    vector_allowlist: str
    vector_cache_ttl_sec: int
    vector_top_k: int
    vector_similarity_threshold: float

    # ── Embedding ──
    embedding_provider: str
    embedding_api_key_configured: bool = False
    embedding_api_key_masked: str = ""
    embedding_base_url: str
    embedding_model: str
    embedding_dim: int
    embedding_timeout: int
    embedding_batch_size: int

    # ── Metadata ──
    updated_at: datetime | None = None


class VectorConfigPatchRequest(BaseModel):
    """部分更新向量配置。所有字段可选，只更新提供的字段。"""

    # ── Vector Search ──
    vector_enabled: bool | None = None
    vector_mode: str | None = Field(default=None, pattern="^(off|shadow|allowlist|all)$")
    vector_allowlist: str | None = None
    vector_cache_ttl_sec: int | None = Field(default=None, ge=0, le=86400)
    vector_top_k: int | None = Field(default=None, ge=1, le=10000)
    vector_similarity_threshold: float | None = Field(default=None, ge=0.0, le=1.0)

    # ── Embedding ──
    embedding_provider: str | None = None
    embedding_api_key: SecretStr | None = None  # null/None = 不修改, 空字符串 = 清除
    embedding_base_url: str | None = None
    embedding_model: str | None = None
    embedding_dim: int | None = Field(default=None, ge=1, le=8192)
    embedding_timeout: int | None = Field(default=None, ge=1, le=300)
    embedding_batch_size: int | None = Field(default=None, ge=1, le=256)

    def get_embedding_api_key_value(self) -> str | None:
        """Return the plaintext embedding API key, handling None, mask, and empty."""
        if self.embedding_api_key is None:
            return None  # not provided — keep existing
        val = self.embedding_api_key.get_secret_value()
        if is_mask_placeholder(val):
            return None  # mask — keep existing
        return val  # may be "" (explicit clear) or a real key


class EmbeddingTestRequest(BaseModel):
    """测试 Embedding API 连通性。api_key 为空时从 DB 读取已存储的 key。"""

    api_base_url: str
    api_key: SecretStr | None = None
    model: str
    dim: int = 1024
    timeout: int = 30

    def get_api_key_value(self) -> str | None:
        if self.api_key is None:
            return None
        val = self.api_key.get_secret_value()
        if not val or is_mask_placeholder(val):
            return None
        return val


class EmbeddingTestResponse(BaseModel):
    """Embedding API 连通性测试结果。"""

    success: bool
    status: str  # ok | auth_error | network_error | timeout | dimension_mismatch | format_error
    message: str = ""
    latency_ms: int = 0
    returned_dim: int | None = None
