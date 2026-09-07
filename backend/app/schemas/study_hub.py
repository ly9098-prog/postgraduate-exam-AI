"""408 智能学习中心响应模型。"""

from typing import Literal

from pydantic import Field

from app.schemas.base import BaseModel

StudyHubTaskType = Literal[
    "review",
    "weakness",
    "hard_questions",
    "knowledge_path",
    "smart_practice",
]

StudyHubRoute = Literal["review_today", "practice"]


class StudyHubTask(BaseModel):
    key: str
    task_type: StudyHubTaskType
    priority: int
    title: str
    reason: str
    action_label: str
    route: StudyHubRoute
    route_params: dict = Field(default_factory=dict)
    estimated_question_count: int = 0
    estimated_minutes: int = 0
    subject_id: int | None = None
    subject_code: str | None = None
    subject_name: str | None = None
    knowledge_point_id: int | None = None
    knowledge_point_name: str | None = None
    question_ids: list[int] = Field(default_factory=list)


class StudyHubSubjectMastery(BaseModel):
    subject_id: int
    subject_code: str
    subject_name: str
    data_available: bool = False
    mastery_score: float | None = None
    confidence: float = 0.0
    attempt_count: int = 0
    accuracy: float | None = None


class StudyHubReviewSummary(BaseModel):
    due_count: int = 0
    completed_count: int = 0
    remaining_count: int = 0
    overdue_count: int = 0
    estimated_minutes: int = 0


class StudyHubOverviewResponse(BaseModel):
    date: str
    scope: str = "exam408"
    scope_ready: bool = True
    fallback_used: bool = False
    today_question_count: int = 0
    total_practice_count: int = 0
    review: StudyHubReviewSummary = Field(default_factory=StudyHubReviewSummary)
    primary_task: StudyHubTask
    tasks: list[StudyHubTask] = Field(default_factory=list)
    subject_mastery: list[StudyHubSubjectMastery] = Field(default_factory=list)
