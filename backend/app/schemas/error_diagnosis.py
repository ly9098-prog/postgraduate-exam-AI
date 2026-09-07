from datetime import datetime

from pydantic import Field, field_validator, model_validator

from app.schemas.base import BaseModel

ERROR_TYPES = (
    "knowledge_gap",
    "concept_confusion",
    "memory_error",
    "calculation_error",
    "misread",
    "reasoning_error",
    "time_pressure",
    "careless",
    "unknown",
)


class ErrorTaxonomyItem(BaseModel):
    type: str
    label: str
    description: str = ""


class ErrorDiagnosisConfirmRequest(BaseModel):
    diagnosis_id: int | None = Field(default=None, gt=0)
    primary_type: str
    secondary_types: list[str] = Field(default_factory=list, max_length=3)

    @field_validator("primary_type")
    @classmethod
    def validate_primary(cls, value: str) -> str:
        value = str(value or "").strip()
        if value not in ERROR_TYPES:
            raise ValueError("unsupported error diagnosis type")
        return value

    @field_validator("secondary_types")
    @classmethod
    def validate_secondary(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        for raw in values or []:
            value = str(raw or "").strip()
            if value not in ERROR_TYPES or value == "unknown":
                raise ValueError("unsupported secondary error diagnosis type")
            if value not in result:
                result.append(value)
        return result

    @model_validator(mode="after")
    def secondary_must_differ(self):
        self.secondary_types = [
            value for value in self.secondary_types if value != self.primary_type
        ]
        return self


class ErrorDiagnosisResponse(BaseModel):
    id: int
    wrong_question_id: int
    question_id: int
    question_version_id: int
    practice_record_id: int | None = None
    exam_answer_id: int | None = None
    source_context: str
    occurred_at: datetime
    taxonomy_version: str
    classification_version: int

    primary_type: str
    primary_label: str
    secondary_types: list[str] = []
    secondary_labels: list[str] = []
    effective_source: str
    user_confirmed: bool = False
    confirmed_at: datetime | None = None

    ai_status: str
    ai_primary_type: str | None = None
    ai_primary_label: str | None = None
    ai_secondary_types: list[str] = []
    ai_secondary_labels: list[str] = []
    ai_confidence: float | None = None
    ai_reason: str | None = None
    ai_model: str | None = None
    ai_suggested_at: datetime | None = None


class ErrorDiagnosisSuggestResponse(BaseModel):
    queued: bool = False
    diagnosis: ErrorDiagnosisResponse


class ErrorDiagnosisTypeStats(BaseModel):
    type: str
    label: str
    count: int = 0
    percent: float = 0.0
    confirmed_count: int = 0


class ErrorDiagnosisSubjectStats(BaseModel):
    subject_id: int
    subject_code: str = ""
    subject_name: str = ""
    count: int = 0
    top_type: str = "unknown"
    top_label: str = "暂未分类"
    top_count: int = 0


class ErrorDiagnosisKnowledgeStats(BaseModel):
    knowledge_point_id: int
    name: str
    count: int = 0
    top_type: str = "unknown"
    top_label: str = "暂未分类"
    top_count: int = 0


class ErrorDiagnosisChangeStats(BaseModel):
    type: str
    label: str
    current_count: int = 0
    previous_count: int = 0
    delta: int = 0


class ErrorDiagnosisStatsResponse(BaseModel):
    taxonomy_version: str
    window_days: int
    total_errors: int = 0
    classified_count: int = 0
    confirmed_count: int = 0
    unknown_count: int = 0
    by_type: list[ErrorDiagnosisTypeStats] = []
    by_subject: list[ErrorDiagnosisSubjectStats] = []
    by_knowledge_point: list[ErrorDiagnosisKnowledgeStats] = []
    changes: list[ErrorDiagnosisChangeStats] = []
