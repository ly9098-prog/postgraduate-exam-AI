"""Stage 7 审核系统 — Pydantic schemas."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


# --- submit_to_review ---

class Stage5Question(BaseModel):
    """Stage 5/6 输出的单道题目。"""
    stem: str
    options: list[dict] = []
    answer: str = ""
    analysis: str = ""
    question_type: str = "single_choice"
    subject: str = ""
    confidence_score: float = 0.0
    is_valid: bool = True
    errors: list[str] = []
    warnings: list[str] = []
    source: dict[str, Any] = {}
    knowledge_points: list[str] = []
    difficulty: int = 3
    stem_hash: str = ""


class BatchMeta(BaseModel):
    source_type: str = "pdf"
    source_file: str = ""
    subject: str = ""


class SubmitReviewRequest(BaseModel):
    questions: list[Stage5Question]
    batch_meta: BatchMeta = BatchMeta()


class SubmitReviewItem(BaseModel):
    id: int
    status: str
    confidence_score: float
    stem_preview: str
    has_issues: bool


class SubmitReviewResponse(BaseModel):
    batch_id: str
    total: int
    written: int
    skipped: int
    items: list[SubmitReviewItem]


# --- review-queue ---

class ReviewQueueItem(BaseModel):
    """审核队列中的单条记录。"""
    id: int
    batch_id: str
    source_type: str
    source_file: str | None = None
    subject: str | None = None
    question_type: str | None = None
    parsed_content: dict | None = None
    parsed_options: dict | None = None
    parsed_answer: str | None = None
    parsed_analysis: str | None = None
    status: str
    ai_confidence: float | None = None
    review_note: str | None = None
    ai_metadata: dict | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class ReviewQueueResponse(BaseModel):
    items: list[ReviewQueueItem]
    total: int
    page: int
    page_size: int


# --- fix ---

class FixQuestionRequest(BaseModel):
    stem: str | None = None
    options: list[dict] | None = None
    answer: str | None = None
    analysis: str | None = None


class FixQuestionResponse(BaseModel):
    id: int
    status: str
    updated_fields: list[str]


# --- pipeline ---

class PipelineUploadResponse(BaseModel):
    pipeline_id: str
    status: str


class PipelineStatusResponse(BaseModel):
    pipeline_id: str
    status: str
    stages: dict[str, Any] = {}
    stats: dict[str, Any] = {}
    errors: list[str] = []
    batch_id: str = ""
    started_at: str = ""
    finished_at: str = ""
