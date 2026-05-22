from datetime import datetime

from pydantic import BaseModel, Field


class EnrichResponse(BaseModel):
    from_fallback: bool
    ai_metadata: dict
    tokens_used: int = 0
    duration_ms: int = 0


class EnrichBatchResponse(BaseModel):
    processed: int
    succeeded: int
    fallback: int


class GenerateRequest(BaseModel):
    subject: str
    knowledge_points: list[str] = Field(default_factory=list)
    difficulty: int = 3
    count: int = 3
    question_type: str = "choice"
    extra_hint: str | None = None


class GenerateResponse(BaseModel):
    batch_id: str
    generated: int
    from_fallback: bool
    tokens_used: int = 0
    duration_ms: int = 0


class CompleteResponse(BaseModel):
    missing: list[str]
    from_fallback: bool
    ai_metadata: dict
    tokens_used: int = 0
    duration_ms: int = 0


class AiLogItem(BaseModel):
    id: int
    user_id: int
    action: str
    target_type: str | None = None
    target_id: int | None = None
    batch_id: str | None = None
    confidence: float | None = None
    model: str
    tokens_used: int
    duration_ms: int
    success: int
    error_message: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class AiLogListResponse(BaseModel):
    items: list[AiLogItem]
    page: int
    pageSize: int
