from datetime import datetime

from pydantic import BaseModel, Field


class WrongQuestionCreate(BaseModel):
    question_id: int
    wrong_answer: str
    error_type: str = "other"


class WrongQuestionUpdate(BaseModel):
    error_type: str | None = None


class WrongQuestionQualityUpdate(BaseModel):
    quality: int = Field(..., ge=0, le=5)


class WrongQuestionResponse(BaseModel):
    id: int
    question_id: int
    wrong_answer: str | None = None
    error_type: str
    review_count: int
    created_at: datetime
    updated_at: datetime
    # 关联的题目信息
    subject: str | None = None
    content: dict | None = None
    options: dict | None = None
    answer: str | None = None
    analysis: str | None = None
    knowledge_points: list | None = None


class WrongQuestionStats(BaseModel):
    total: int
    unmastered: int = 0
    by_subject: list[dict]
    by_error_type: list[dict]
