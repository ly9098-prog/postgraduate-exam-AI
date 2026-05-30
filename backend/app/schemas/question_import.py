from datetime import datetime

from pydantic import BaseModel


class QuestionImportResponse(BaseModel):
    id: int
    batch_id: str
    source_type: str
    source_file: str | None = None
    subject: str | None = None
    question_type: str | None = None
    parsed_content: dict | None = None
    parsed_options: dict | None = None
    parsed_answer: str | None = None
    parsed_analysis: str | None = None
    question_hash: str | None = None
    duplicate_status: str = "normal"
    duplicate_of_question_id: int | None = None
    duplicate_of_import_id: int | None = None
    status: str
    review_note: str | None = None
    question_id: int | None = None
    ai_generated: bool = False
    ai_source: str | None = None
    ai_confidence: float | None = None
    ai_metadata: dict | None = None
    ai_answer_flag: bool = False
    created_at: datetime

    class Config:
        from_attributes = True


class ImportBatchResponse(BaseModel):
    batch_id: str
    source_type: str
    source_file: str | None = None
    total: int
    pending: int
    approved: int
    rejected: int
    created_at: datetime


class ImportBatchDetailResponse(BaseModel):
    batch_id: str
    source_type: str
    source_file: str | None = None
    source: str | None = None
    questions: list[QuestionImportResponse]


class ImportQuestionUpdate(BaseModel):
    subject: str | None = None
    question_type: str | None = None
    parsed_content: dict | None = None
    parsed_options: dict | None = None
    parsed_answer: str | None = None
    parsed_analysis: str | None = None
    knowledge_points: list[str] | None = None
    difficulty: int | None = None
    status: str = "approved"
    review_note: str | None = None


class ImportUploadResponse(BaseModel):
    batch_id: str
    total: int
    source_type: str
    source_file: str | None = None
