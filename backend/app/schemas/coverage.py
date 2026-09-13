from typing import Literal

from pydantic import Field

from app.schemas.base import BaseModel

CoverageStatus = Literal["empty", "insufficient", "imbalanced", "healthy"]
ExamYearCoverageStatus = Literal["missing", "draft", "invalid", "complete", "archived"]


class CoverageSyllabusSummary(BaseModel):
    id: int
    code: str
    name: str
    effective_year: int


class CoverageMatrixItem(BaseModel):
    syllabus_knowledge_point_id: int
    knowledge_point_id: int
    subject_id: int
    subject_code: str
    subject_name: str
    name: str
    total_question_count: int = 0
    past_exam_choice_count: int = 0
    mock_choice_count: int = 0
    difficulty_easy_count: int = 0
    difficulty_medium_count: int = 0
    difficulty_hard_count: int = 0
    question_type_counts: dict[str, int] = Field(default_factory=dict)
    years: list[int] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    missing_analysis_count: int = 0
    duplicate_suspect_count: int = 0
    status: CoverageStatus
    issues: list[str] = Field(default_factory=list)


class CoverageSummary(BaseModel):
    min_questions: int
    total_knowledge_points: int = 0
    healthy_knowledge_points: int = 0
    empty_knowledge_points: int = 0
    insufficient_knowledge_points: int = 0
    imbalanced_knowledge_points: int = 0
    total_questions: int = 0
    mapped_questions: int = 0
    unmapped_questions: int = 0
    missing_analysis_questions: int = 0
    image_reference_anomaly_questions: int = 0
    duplicate_suspect_questions: int = 0
    unversioned_questions: int = 0
    syllabus_snapshot_missing_questions: int = 0


class CoverageDuplicateGroup(BaseModel):
    question_hash: str
    question_ids: list[int] = Field(default_factory=list)


class CoverageQualityIssues(BaseModel):
    unmapped_question_ids: list[int] = Field(default_factory=list)
    missing_analysis_question_ids: list[int] = Field(default_factory=list)
    image_reference_anomaly_question_ids: list[int] = Field(default_factory=list)
    unversioned_question_ids: list[int] = Field(default_factory=list)
    syllabus_snapshot_missing_question_ids: list[int] = Field(default_factory=list)
    duplicate_groups: list[CoverageDuplicateGroup] = Field(default_factory=list)


class ExamYearCoverageItem(BaseModel):
    year: int
    status: ExamYearCoverageStatus
    paper_id: int | None = None
    paper_ref: str | None = None
    paper_title: str | None = None
    paper_status: str | None = None
    paper_version: int | None = None
    question_count: int = 0
    total_choice_score: float = 0.0
    missing_analysis_count: int = 0
    missing_knowledge_point_count: int = 0
    validation_errors: list[str] = Field(default_factory=list)
    quality_warnings: list[str] = Field(default_factory=list)


class CoverageReportResponse(BaseModel):
    syllabus: CoverageSyllabusSummary
    summary: CoverageSummary
    items: list[CoverageMatrixItem] = Field(default_factory=list)
    exam_years: list[ExamYearCoverageItem] = Field(default_factory=list)
    quality_issues: CoverageQualityIssues
    knowledge_graph_quality: dict = Field(default_factory=dict)
