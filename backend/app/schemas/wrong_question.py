from app.schemas.base import BaseModel
from datetime import datetime
from enum import StrEnum

from pydantic import Field, field_validator

# ── 枚举 ──


class BatchAction(StrEnum):
    ADD_TO_REVIEW = "add_to_review"
    MARK_MASTERED = "mark_mastered"
    UNMARK_MASTERED = "unmark_mastered"
    REMOVE_FROM_BOOK = "remove_from_book"
    DELETE = "delete"


# ── 创建 / 更新 ──


class WrongQuestionCreate(BaseModel):
    question_id: int
    wrong_answer: str
    error_type: str = "other"


class WrongQuestionUpdate(BaseModel):
    error_type: str | None = None


class WrongQuestionQualityUpdate(BaseModel):
    quality: int = Field(..., ge=0, le=5)


# ── 响应 ──


class WrongQuestionResponse(BaseModel):
    id: int
    question_id: int
    wrong_answer: str | None = None
    error_type: str
    review_count: int
    created_at: datetime
    updated_at: datetime
    # 关联的题目信息
    subject_id: int | None = None
    subject_code: str | None = None
    subject_name: str | None = None
    question_type: str | None = None
    content: dict | None = None
    options: dict | None = None
    answer: str | None = None
    analysis: str | None = None
    knowledge_points: list | None = None
    image_url: list | None = None
    # AI 分析（已持久化的结果）
    ai_analysis: dict | None = None
    ai_analysis_status: str | None = None  # "ready" | "empty" | "stale" | "fallback" | "generating"
    # 扩展字段
    wrong_count: int = 0
    review_record_count: int = 0            # 真实复习次数（from ReviewRecord）
    mastery_percent: float = 0.0
    is_mastered: bool = False
    next_review_at: datetime | None = None
    last_reviewed_at: datetime | None = None
    last_wrong_at: datetime | None = None


# ── 统计 ──


class WrongQuestionStats(BaseModel):
    total: int
    unmastered: int = 0
    mastered: int = 0
    high_frequency_count: int = 0
    today_due_count: int = 0
    by_subject: list[dict]
    by_error_type: list[dict]


# ── 批量操作 ──


class WrongQuestionBatchRequest(BaseModel):
    action: BatchAction
    ids: list[int] = Field(..., min_length=1, max_length=100)

    @field_validator("ids")
    @classmethod
    def deduplicate_ids(cls, v: list[int]) -> list[int]:
        return list(dict.fromkeys(v))


class WrongQuestionBatchResponse(BaseModel):
    success: bool
    action: str
    requested_count: int
    updated_count: int
    skipped_count: int
    skipped_ids: list[int] = []


# ── 任务流 ──


class TaskFlowGroup(BaseModel):
    key: str
    title: str
    total: int
    items: list[WrongQuestionResponse] = []


class TaskFlowSummary(BaseModel):
    total_count: int
    mastered_count: int
    high_frequency_count: int
    today_due_count: int


class TaskFlowResponse(BaseModel):
    summary: TaskFlowSummary
    groups: list[TaskFlowGroup]
