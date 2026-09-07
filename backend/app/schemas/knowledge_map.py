"""408 knowledge mastery map response models."""

from typing import Literal

from pydantic import Field

from app.schemas.base import BaseModel
from app.schemas.syllabus import ActiveSyllabusSummary

KnowledgeMapStatus = Literal[
    "no_data",
    "insufficient",
    "weak",
    "developing",
    "good",
    "mastered",
]


class KnowledgeMapSubjectSummary(BaseModel):
    subject_id: int
    subject_code: str
    subject_name: str
    status: KnowledgeMapStatus
    mastery_score: float | None = None
    confidence: float = 0.0
    total_knowledge_points: int = 0
    trainable_knowledge_points: int = 0
    observed_knowledge_points: int = 0
    reliable_knowledge_points: int = 0
    weak_knowledge_points: int = 0
    attempt_count: int = 0
    correct_count: int = 0
    accuracy: float | None = None
    coverage_ratio: float = 0.0


class KnowledgeMapOverviewResponse(BaseModel):
    scope: str = "exam408"
    syllabus_version: ActiveSyllabusSummary | None = None
    scope_ready: bool = True
    subjects: list[KnowledgeMapSubjectSummary] = Field(default_factory=list)


class KnowledgeMapNode(BaseModel):
    knowledge_point_id: int
    name: str
    description: str | None = None
    difficulty_level: int = 3
    parent_id: int | None = None
    depth: int = 0
    child_count: int = 0
    trainable_question_count: int = 0
    status: KnowledgeMapStatus
    mastery_score: float | None = None
    confidence: float = 0.0
    attempt_count: int = 0
    correct_count: int = 0
    wrong_count: int = 0
    accuracy: float | None = None
    recent_wrong_count: int = 0
    last_practiced_at: str | None = None


class KnowledgeMapSubjectResponse(BaseModel):
    scope: str = "exam408"
    syllabus_version: ActiveSyllabusSummary | None = None
    subject: KnowledgeMapSubjectSummary
    nodes: list[KnowledgeMapNode] = Field(default_factory=list)


class KnowledgeMapRelation(BaseModel):
    knowledge_point_id: int
    name: str
    relation_type: str
    confidence: float = 0.0
    weight: float = 0.0


class KnowledgeMapRecentAnswer(BaseModel):
    is_correct: bool
    used_time: int | None = None
    answered_at: str | None = None


class KnowledgeMapPointDetailResponse(BaseModel):
    scope: str = "exam408"
    syllabus_version: ActiveSyllabusSummary | None = None
    subject_id: int
    subject_code: str
    subject_name: str
    knowledge_point_id: int
    name: str
    description: str | None = None
    difficulty_level: int = 3
    status: KnowledgeMapStatus
    mastery_score: float | None = None
    confidence: float = 0.0
    attempt_count: int = 0
    correct_count: int = 0
    wrong_count: int = 0
    accuracy: float | None = None
    recent_wrong_count: int = 0
    last_practiced_at: str | None = None
    last_wrong_at: str | None = None
    trainable_question_count: int = 0
    recent_answers: list[KnowledgeMapRecentAnswer] = Field(default_factory=list)
    prerequisites: list[KnowledgeMapRelation] = Field(default_factory=list)
    next_nodes: list[KnowledgeMapRelation] = Field(default_factory=list)
    related_nodes: list[KnowledgeMapRelation] = Field(default_factory=list)
    practice_route_params: dict = Field(default_factory=dict)
