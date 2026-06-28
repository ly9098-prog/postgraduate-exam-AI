"""Phase 2 — 知识点画像 + 推荐反馈 Schema。"""
from datetime import datetime

from pydantic import BaseModel, Field


# ── 用户知识点掌握状态 ──

class KnowledgeStateItem(BaseModel):
    knowledge_point_id: int
    name: str
    subject: str
    attempt_count: int
    correct_count: int
    wrong_count: int
    accuracy: float
    mastery_score: float
    weakness_level: str
    last_practiced_at: str | None = None
    last_wrong_at: str | None = None


class WeakKnowledgePointItem(BaseModel):
    knowledge_point_id: int | None = None
    name: str
    mastery_score: float
    accuracy: float
    attempt_count: int
    weakness_level: str


# ── 推荐反馈 ──

class RecommendationFeedbackRequest(BaseModel):
    question_id: int
    request_id: str | None = None
    event: str = Field(..., pattern="^(shown|clicked|answered)$")
    is_correct: bool | None = None


class RecommendationFeedbackResponse(BaseModel):
    status: str
    matched: bool = False


# ── 管理端知识点 backfill ──

class KnowledgeBackfillRequest(BaseModel):
    subject: str | None = None
    limit: int = Field(500, ge=1, le=5000)


class KnowledgeBackfillResponse(BaseModel):
    total_questions: int
    created: int
    skipped: int
    errors: list[dict] = []


class KnowledgeStatusResponse(BaseModel):
    total_knowledge_points: int
    total_question_mappings: int
    mapped_questions: int
    unmapped_questions: int
