from pydantic import BaseModel


class ErrorAnalysisRequest(BaseModel):
    wrong_question_id: int


class StudyAdviceRequest(BaseModel):
    subject: str | None = None


class AiResponse(BaseModel):
    session_type: str
    content: dict
    tokens_used: int
    model: str
    duration_ms: int
    from_cache: bool = False
    from_fallback: bool = False


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
