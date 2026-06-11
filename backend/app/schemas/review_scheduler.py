from datetime import datetime

from pydantic import BaseModel, Field


class ReviewQuestion(BaseModel):
    schedule_id: int
    question_id: int
    subject: str
    question_type: str
    stem: str
    options: dict = {}
    content: dict | None = None
    interval: int
    repetitions: int
    ease_factor: float


class GradeSubmit(BaseModel):
    schedule_id: int
    question_id: int
    user_answer: str


class TodayReviewResponse(BaseModel):
    total_today: int
    questions: list[ReviewQuestion]


class ReviewSubmit(BaseModel):
    schedule_id: int
    question_id: int
    rating: int = Field(..., ge=0, le=5)


class ReviewSubmitResponse(BaseModel):
    schedule_id: int
    question_id: int
    rating: int
    interval_after: int
    ease_factor_after: float
    next_review_at: datetime
    is_correct: bool


class BatchReviewRequest(BaseModel):
    reviews: list[ReviewSubmit]


class BatchReviewResult(BaseModel):
    schedule_id: int
    question_id: int
    next_review_at: datetime
    is_correct: bool


class BatchReviewResponse(BaseModel):
    results: list[BatchReviewResult]
    total: int


class SubjectReviewStats(BaseModel):
    scheduled: int
    reviewed: int
    remaining: int


class ReviewStatsResponse(BaseModel):
    total_scheduled: int
    total_reviewed_today: int
    remaining_today: int
    overdue: int
    accuracy_last_7d: float
    by_subject: dict[str, SubjectReviewStats] = {}


class ReviewHistoryItem(BaseModel):
    question_id: int
    rating: int
    interval_after: int
    reviewed_at: datetime


class ReviewHistoryResponse(BaseModel):
    items: list[ReviewHistoryItem]
    total: int
    page: int
    page_size: int


class BatchGradeItem(BaseModel):
    schedule_id: int
    question_id: int
    user_answer: str = ""


class BatchGradeRequest(BaseModel):
    reviews: list[BatchGradeItem]


class BatchGradeResult(BaseModel):
    schedule_id: int
    question_id: int
    is_correct: bool
    correct_answer: str
    rating: int
    interval_after: int
    ease_factor_after: float
    next_review_at: datetime


class BatchGradeResponse(BaseModel):
    results: list[BatchGradeResult]
    total: int
    correct_count: int
    wrong_count: int


class MasterUnmasterResponse(BaseModel):
    schedule_id: int
    mastered: bool
