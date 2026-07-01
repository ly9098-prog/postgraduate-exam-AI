"""V5 学习报告 Schema"""
from datetime import datetime

from pydantic import BaseModel


# ── Overview ──


class StudyOverviewResponse(BaseModel):
    today_answer_count: int = 0
    today_correct_count: int = 0
    today_accuracy: float = 0.0

    recent_answer_count: int = 0
    recent_correct_count: int = 0
    recent_accuracy: float = 0.0

    total_answer_count: int = 0
    total_correct_count: int = 0
    total_accuracy: float = 0.0

    due_review_count: int = 0
    overdue_review_count: int = 0

    weak_knowledge_count: int = 0
    unstable_knowledge_count: int = 0
    mastered_knowledge_count: int = 0

    wrong_question_count: int = 0
    repeated_wrong_question_count: int = 0


# ── Review Plan ──


class ReviewPlanItem(BaseModel):
    question_id: int
    knowledge_point_id: int | None = None
    knowledge_point_name: str | None = None
    box_level: int = 0
    wrong_count: int = 0
    correct_count: int = 0
    next_review_at: datetime | None = None
    overdue_days: int = 0
    priority: str = "normal"


class ReviewPlanResponse(BaseModel):
    due_count: int = 0
    overdue_count: int = 0
    today_recommended_count: int = 0
    items: list[ReviewPlanItem] = []


# ── Leitner Distribution ──


class LeitnerBoxItem(BaseModel):
    box_level: int
    label: str
    description: str
    count: int = 0


class LeitnerDistributionResponse(BaseModel):
    boxes: list[LeitnerBoxItem] = []
    total_tracked_questions: int = 0


# ── Knowledge Mastery ──


class KnowledgeMasterySummary(BaseModel):
    weak_count: int = 0
    normal_count: int = 0
    good_count: int = 0
    mastered_count: int = 0
    unknown_count: int = 0


class KnowledgeMasteryItem(BaseModel):
    knowledge_point_id: int
    knowledge_point_name: str
    mastery_score: float = 0.0
    confidence: float = 0.0
    answer_count: int = 0
    correct_count: int = 0
    wrong_count: int = 0
    recent_wrong_count: int = 0
    last_practiced_at: datetime | None = None
    status: str = "unknown"
    suggestion: str = ""


class KnowledgeMasteryResponse(BaseModel):
    summary: KnowledgeMasterySummary
    items: list[KnowledgeMasteryItem] = []


# ── Wrong Questions ──


class WrongQuestionItem(BaseModel):
    question_id: int
    title: str = ""
    knowledge_point_id: int | None = None
    knowledge_point_name: str | None = None
    wrong_count: int = 0
    correct_count: int = 0
    answer_count: int = 0
    last_answered_at: datetime | None = None
    next_review_at: datetime | None = None
    box_level: int = 0
    status: str = "needs_review"


class WrongQuestionSummaryResponse(BaseModel):
    wrong_question_count: int = 0
    repeated_wrong_question_count: int = 0
    items: list[WrongQuestionItem] = []


# ── Study Trend ──


class StudyTrendItem(BaseModel):
    date: str
    answer_count: int = 0
    correct_count: int = 0
    wrong_count: int = 0
    accuracy: float = 0.0


class StudyTrendResponse(BaseModel):
    days: int
    items: list[StudyTrendItem] = []
