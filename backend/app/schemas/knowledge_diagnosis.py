"""Knowledge-map diagnosis, chapter practice report and actionable recommendations."""

from typing import Literal

from pydantic import Field

from app.schemas.base import BaseModel

KnowledgeDiagnosisKind = Literal["build", "strengthen", "review", "maintain"]


class KnowledgeDiagnosisRecommendation(BaseModel):
    rank: int
    kind: KnowledgeDiagnosisKind
    knowledge_point_id: int
    knowledge_point_name: str
    depth: int = 0
    priority_score: float = 0.0
    title: str
    reason: str
    action_label: str = "开始章节专项"
    mastery_score: float | None = None
    coverage_ratio: float = 0.0
    weak_knowledge_points: int = 0
    trainable_knowledge_points: int = 0
    reliable_knowledge_points: int = 0
    last_chapter_practiced_at: str | None = None
    chapter_session_count: int = 0
    route: str = "practice"
    route_params: dict = Field(default_factory=dict)


class KnowledgeDiagnosisChapterReportItem(BaseModel):
    knowledge_point_id: int
    knowledge_point_name: str
    mastery_score: float | None = None
    coverage_ratio: float = 0.0
    weak_knowledge_points: int = 0
    reliable_knowledge_points: int = 0
    trainable_knowledge_points: int = 0
    session_count: int = 0
    last_7_days_session_count: int = 0
    question_count: int = 0
    correct_count: int = 0
    accuracy: float | None = None
    scope_served_knowledge_point_count: int = 0
    scope_resolved_knowledge_point_count: int = 0
    scope_coverage_ratio: float | None = None
    last_practiced_at: str | None = None


class KnowledgeDiagnosisRecentSession(BaseModel):
    request_id: str
    root_knowledge_point_id: int
    root_name: str
    question_count: int = 0
    correct_count: int = 0
    accuracy: float | None = None
    served_knowledge_point_count: int = 0
    resolved_knowledge_point_count: int = 0
    scope_coverage_ratio: float | None = None
    finished_at: str


class KnowledgeDiagnosisReportSummary(BaseModel):
    period_days: int
    session_count: int = 0
    last_7_days_session_count: int = 0
    question_count: int = 0
    correct_count: int = 0
    accuracy: float | None = None
    practiced_chapter_count: int = 0
    served_knowledge_point_count: int = 0
    scope_served_knowledge_point_count: int = 0
    scope_resolved_knowledge_point_count: int = 0
    scope_coverage_ratio: float | None = None
    current_coverage_ratio: float = 0.0
    current_reliable_knowledge_points: int = 0
    current_trainable_knowledge_points: int = 0
    current_weak_knowledge_points: int = 0


class KnowledgeDiagnosisResponse(BaseModel):
    scope: str = "exam408"
    subject_id: int
    subject_code: str
    subject_name: str
    period_days: int
    generated_at: str
    primary_recommendation: KnowledgeDiagnosisRecommendation | None = None
    recommendations: list[KnowledgeDiagnosisRecommendation] = Field(default_factory=list)
    report: KnowledgeDiagnosisReportSummary
    chapters: list[KnowledgeDiagnosisChapterReportItem] = Field(default_factory=list)
    recent_sessions: list[KnowledgeDiagnosisRecentSession] = Field(default_factory=list)
