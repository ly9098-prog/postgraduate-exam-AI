"""Phase 2 — 知识点画像 + 推荐反馈 Schema。"""

from pydantic import Field
from app.schemas.base import BaseModel

# ── 用户知识点掌握状态 ──

class KnowledgeStateItem(BaseModel):
    knowledge_point_id: int
    name: str
    subject_id: int
    subject_name: str = ""
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


# ── 管理端知识点状态 ──

class KnowledgeStatusResponse(BaseModel):
    total_knowledge_points: int
    total_question_mappings: int
    mapped_questions_all: int
    mapped_questions_active: int
    total_questions_all: int
    total_questions_active: int
    unmapped_questions_all: int
    unmapped_questions_active: int
