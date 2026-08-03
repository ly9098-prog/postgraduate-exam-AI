from datetime import datetime

from pydantic import BaseModel, Field


class ReviewQuestion(BaseModel):
    schedule_id: int
    question_id: int
    subject_id: int | None = None
    subject_code: str = ""
    subject_name: str = ""
    question_type: str
    stem: str
    options: dict = {}
    content: dict = {}
    image_url: list[str] | str | None = None
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
    subject_id: int
    subject_code: str = ""
    subject_name: str = ""
    scheduled: int
    reviewed: int
    remaining: int


class ReviewStatsResponse(BaseModel):
    total_scheduled: int
    total_reviewed_today: int
    remaining_today: int
    overdue: int
    accuracy_last_7d: float
    by_subject: list[SubjectReviewStats] = []


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


# ── Today review task flow (overview / next-batch / result) ──


class TodayReviewOverviewResponse(BaseModel):
    date: str
    today_due_count: int
    today_completed_count: int
    today_remaining_count: int
    today_overdue_count: int
    today_new_due_count: int
    estimated_minutes: int
    batch_size: int
    current_batch_no: int
    total_batch_count: int
    remaining_batch_count: int
    all_question_ids: list[int] = []
    completed_question_ids: list[int] = []
    remaining_question_ids: list[int] = []
    has_due_review: bool = False
    is_completed: bool = False


class NextBatchRequest(BaseModel):
    batch_size: int = Field(default=10, ge=1, le=40)


class NextBatchResponse(BaseModel):
    session_id: str = ""
    group_id: str = ""
    batch_no: int = 1
    total_batch_count: int = 0
    batch_size: int = 0
    today_due_count: int = 0
    today_completed_count: int = 0
    today_remaining_count: int = 0
    questions: list[ReviewQuestion] = []


class TodayReviewResultResponse(BaseModel):
    date: str
    today_due_count: int
    today_completed_count: int
    correct_count: int
    wrong_count: int
    skipped_count: int = 0
    mastered_count: int = 0
    accuracy: float = 0.0
    completion_rate: float = 0.0
    updated_schedule_count: int = 0
    tomorrow_due_count: int = 0
    subject_stats: list[dict] = []
    is_completed: bool = False
