"""向量功能相关 Pydantic 模型。"""

from pydantic import BaseModel, Field


class EmbeddingBackfillRequest(BaseModel):
    subject: str | None = None
    limit: int = Field(default=100, ge=1, le=1000)
    force: bool = False


class EmbeddingBackfillResponse(BaseModel):
    enabled: bool
    total: int
    created: int
    updated: int
    skipped: int
    failed: int
    errors: list[str] = []


class EmbeddingStatusResponse(BaseModel):
    vector_enabled: bool
    db_dialect: str
    embedding_model: str
    embedding_dim: int
    total_embeddings: int
    total_questions: int
