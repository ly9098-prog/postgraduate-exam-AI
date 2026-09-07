from __future__ import annotations

from datetime import datetime

from pydantic import Field, model_validator

from app.schemas.base import BaseModel
from app.schemas.exam import ExamPaperStatus, ExamPaperType


class AdminExamPaperCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=128)
    paper_type: ExamPaperType
    year: int | None = Field(default=None, ge=2000, le=2100)
    source: str | None = Field(default=None, max_length=128)
    duration_sec: int | None = Field(default=None, ge=60, le=6 * 60 * 60)

    @model_validator(mode="after")
    def validate_year(self):
        if self.paper_type == "past_exam_choice" and self.year is None:
            raise ValueError("真题选择题卷必须填写年份")
        return self


class AdminExamPaperUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=128)
    paper_type: ExamPaperType | None = None
    year: int | None = Field(default=None, ge=2000, le=2100)
    source: str | None = Field(default=None, max_length=128)
    duration_sec: int | None = Field(default=None, ge=60, le=6 * 60 * 60)
    is_active: bool | None = None

    @model_validator(mode="after")
    def require_field(self):
        if not self.model_fields_set:
            raise ValueError("至少提供一个更新字段")
        return self


class AdminExamPaperItemInput(BaseModel):
    question_id: int = Field(gt=0)
    score: float = Field(gt=0, le=100)


class AdminExamPaperItemsReplaceRequest(BaseModel):
    items: list[AdminExamPaperItemInput] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_questions(self):
        ids = [item.question_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("同一试卷不能重复添加题目")
        return self


class AdminExamPaperListItem(BaseModel):
    id: int
    title: str
    paper_type: ExamPaperType
    year: int | None = None
    source: str | None = None
    duration_sec: int | None = None
    version: int
    status: ExamPaperStatus
    is_active: bool
    question_count: int
    total_choice_score: float
    attempt_count: int
    published_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class AdminExamPaperQuestionItem(BaseModel):
    id: int
    question_id: int
    question_version_id: int
    position: int
    score: float
    subject_id: int
    subject_code: str
    subject_name: str
    question_type: str
    content: dict
    options: dict | None = None
    year: int | None = None
    source: str | None = None
    difficulty: int = 3
    review_status: str
    is_active: bool
    current_version_id: int | None = None
    version_is_current: bool


class AdminExamPaperDetail(AdminExamPaperListItem):
    items: list[AdminExamPaperQuestionItem] = Field(default_factory=list)
    validation_errors: list[str] = Field(default_factory=list)
