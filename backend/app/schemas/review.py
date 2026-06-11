from datetime import date, datetime

from pydantic import BaseModel, Field


class ReviewSubmitItem(BaseModel):
    wrong_question_id: int
    quality: int = Field(..., ge=0, le=5)


class ReviewSubmitRequest(BaseModel):
    items: list[ReviewSubmitItem]


class ReviewSM2Result(BaseModel):
    efactor: float
    interval: int
    repetitions: int
    next_review_date: date


class ReviewSubmitResult(BaseModel):
    wrong_question_id: int
    quality: int
    sm2: ReviewSM2Result


class ReviewSubmitResponse(BaseModel):
    results: list[ReviewSubmitResult]
    processed: int


class ReviewDueItem(BaseModel):
    id: int
    question_id: int
    wrong_answer: str | None = None
    error_type: str
    review_count: int
    last_review_at: datetime | None = None
    efactor: float
    interval: int
    repetitions: int
    next_review_date: date | None = None
    quality: int | None = None
    # 关联题目信息
    subject: str | None = None
    content: dict | None = None
    options: dict | None = None
    answer: str | None = None
    analysis: str | None = None
    knowledge_points: list | None = None


class ReviewStatsResponse(BaseModel):
    total_wrong: int            # 错题总数
    due_today: int              # 今日待复习
    reviewed_today: int         # 今日已复习
    reviewed_this_week: int     # 本周已复习数
    average_efactor: float      # 平均难度因子
    by_subject: list[dict]      # 按科目统计
