from datetime import date, datetime

from pydantic import BaseModel, Field


class WrongQuestionCreate(BaseModel):
    question_id: int
    wrong_answer: str
    error_type: str = "other"


class WrongQuestionUpdate(BaseModel):
    error_type: str | None = None
    mastered: bool | None = None


class WrongQuestionQualityUpdate(BaseModel):
    quality: int = Field(..., ge=0, le=5)


class WrongQuestionResponse(BaseModel):
    id: int
    question_id: int
    wrong_answer: str | None = None
    error_type: str
    review_count: int
    mastered: bool
    created_at: datetime
    updated_at: datetime
    # SM-2 字段
    efactor: float = 2.5
    interval: int = 0
    repetitions: int = 0
    next_review_date: date | None = None
    quality: int | None = None
    # 关联的题目信息
    subject: str | None = None
    content: dict | None = None
    options: dict | None = None
    answer: str | None = None
    analysis: str | None = None
    knowledge_points: list | None = None


class WrongQuestionStats(BaseModel):
    total: int
    mastered: int
    unmastered: int
    by_subject: list[dict]
    by_error_type: list[dict]
