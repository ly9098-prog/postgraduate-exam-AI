"""向量功能相关 Pydantic 模型。"""

from pydantic import Field

from app.schemas.base import BaseModel


class EmbeddingBackfillRequest(BaseModel):
    subject: str | None = None
    limit: int = Field(default=100, ge=1, le=1000)
    force: bool = False
    dry_run: bool = False
    after_id: int = Field(
        default=0, ge=0, description="游标：从此 question_id 之后开始"
    )


class EmbeddingBackfillError(BaseModel):
    question_id: int
    reason: str


class EmbeddingBackfillResponse(BaseModel):
    enabled: bool
    total: int
    created: int
    updated: int
    skipped: int
    failed: int
    dry_run: bool = False
    would_create: int = 0
    would_update: int = 0
    would_skip: int = 0
    model_id: int | None = None
    embedding_dim: int | None = None
    errors: list = Field(default_factory=list)
    next_cursor: int | None = None
    has_more: bool = False


class EmbeddingStatusResponse(BaseModel):
    configured: bool
    mode: str
    execute_enabled: bool
    result_enabled: bool
    database: str
    extension_installed: bool
    table_exists: bool
    index_exists: bool
    configured_dimension: int
    database_dimension: int | None = None
    dimension_matches: bool | None = None
    embedding_model: str
    embedding_api_configured: bool
    allowlist_configured: bool
    healthy: bool
    issues: list = Field(default_factory=list)
    total_embeddings: int = 0
    total_questions: int = 0
