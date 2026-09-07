from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from app.schemas.base import BaseModel

ExamPaperType = Literal["past_exam_choice", "mock_choice"]
ExamPaperStatus = Literal["draft", "published", "archived"]
ExamAttemptStatus = Literal["in_progress", "submitted", "expired", "abandoned"]


class ExamPaperSummary(BaseModel):
    id: int
    title: str
    paper_type: ExamPaperType
    year: int | None = None
    source: str | None = None
    duration_sec: int | None = None
    version: int
    question_count: int
    total_choice_score: float
    latest_attempt_id: int | None = None
    latest_attempt_status: ExamAttemptStatus | None = None
    best_choice_score: float | None = None


class ExamPaperDetail(ExamPaperSummary):
    subject_distribution: list[dict] = Field(default_factory=list)


class ExamAttemptStartRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128)


class ExamAnswerSaveRequest(BaseModel):
    selected_answer: str | None = Field(default=None, max_length=32)
    marked_for_review: bool | None = None
    used_time: int | None = Field(default=None, ge=0, le=6 * 60 * 60)

    @model_validator(mode="after")
    def require_field(self):
        if not self.model_fields_set:
            raise ValueError("至少提供一个答题字段")
        if self.selected_answer is not None:
            normalized = self.selected_answer.strip().upper()
            self.selected_answer = normalized or None
        return self


class ExamQuestionView(BaseModel):
    item_id: int
    question_id: int
    question_version_id: int
    position: int
    score: float
    subject_id: int
    subject_code: str
    subject_name: str
    question_type: Literal["single_choice"]
    content: dict
    options: dict
    image_url: list | None = None


class ExamSavedAnswer(BaseModel):
    item_id: int
    selected_answer: str | None = None
    marked_for_review: bool = False
    used_time: int = 0
    answered_at: datetime | None = None


class ExamAttemptView(BaseModel):
    id: int
    paper_id: int
    paper_title: str
    paper_type: ExamPaperType
    year: int | None = None
    status: ExamAttemptStatus
    started_at: datetime
    duration_limit_sec: int | None = None
    elapsed_sec: int
    remaining_sec: int | None = None
    question_count: int
    total_choice_score: float
    questions: list[ExamQuestionView]
    answers: list[ExamSavedAnswer]


class ExamAnswerSaveResponse(BaseModel):
    attempt_id: int
    status: ExamAttemptStatus
    answer: ExamSavedAnswer


class ExamResultSubjectBreakdown(BaseModel):
    subject_id: int
    subject_code: str
    subject_name: str
    question_count: int
    answered_count: int
    correct_count: int
    score: float
    total_score: float
    accuracy: float


class ExamResultQuestion(BaseModel):
    item_id: int
    question_id: int
    question_version_id: int
    position: int
    subject_id: int
    subject_code: str
    subject_name: str
    score: float
    earned_score: float
    selected_answer: str | None = None
    correct_answer: str
    is_correct: bool | None = None
    status: Literal["correct", "wrong", "unanswered"]
    marked_for_review: bool = False
    used_time: int = 0
    content: dict
    options: dict
    analysis: str | None = None
    image_url: list | None = None
    knowledge_points: list[str] = Field(default_factory=list)
    wrong_question_id: int | None = None
    error_diagnosis: dict | None = None


class ExamResult(BaseModel):
    attempt_id: int
    paper_id: int
    paper_title: str
    paper_type: ExamPaperType
    year: int | None = None
    attempt_status: ExamAttemptStatus
    started_at: datetime
    submitted_at: datetime
    duration_sec: int
    question_count: int
    answered_count: int
    correct_count: int
    wrong_count: int
    unanswered_count: int
    choice_score: float
    total_choice_score: float
    accuracy: float
    subject_breakdown: list[ExamResultSubjectBreakdown]
    weak_knowledge_points: list[dict] = Field(default_factory=list)
    questions: list[ExamResultQuestion]


class ExamHistoryItem(BaseModel):
    attempt_id: int
    paper_id: int
    paper_title: str
    paper_type: ExamPaperType
    year: int | None = None
    status: ExamAttemptStatus
    started_at: datetime
    submitted_at: datetime | None = None
    duration_sec: int
    question_count: int
    answered_count: int
    correct_count: int
    choice_score: float
    total_choice_score: float
    accuracy: float
