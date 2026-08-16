from app.schemas.base import BaseModel


class ErrorAnalysisRequest(BaseModel):
    wrong_question_id: int
    force_regenerate: bool = False


class StudyAdviceRequest(BaseModel):
    subject_id: int | None = None


class AiResponse(BaseModel):
    session_type: str
    content: dict
    tokens_used: int
    model: str
    duration_ms: int
    from_cache: bool = False
    from_fallback: bool = False
    force_regenerated: bool = False
    cache_preserved: bool = False
    visual_input_count: int = 0
    visual_evidence: str | None = None


class AiPrewarmRequest(BaseModel):
    wrong_question_ids: list[int]


class AiPrewarmResponse(BaseModel):
    queued: list[int]
    skipped: list[int]
    reason: str = "ok"


class AiChatRecord(BaseModel):
    id: int
    session_type: str
    user_message: str
    ai_response: str
    tokens_used: int
    created_at: str


class AiFeedbackRequest(BaseModel):
    source: str  # 'dashboard' | 'wrong_book'
    feedback_type: str
    question_id: int | None = None
    detail: str | None = None
