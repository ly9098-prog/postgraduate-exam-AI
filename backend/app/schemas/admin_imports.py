from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AdminImportBatchListItem(BaseModel):
    batch_id: str
    source_type: str
    source_file: str | None = None
    total_count: int
    pending_count: int
    approved_count: int
    rejected_count: int
    published_count: int
    ai_count: int
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AdminImportQuestionItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    batch_id: str
    source_type: str
    source_file: str | None = None
    subject: str | None = None
    question_type: str | None = None
    raw_data: dict
    parsed_content: dict | None = None
    parsed_options: dict | None = None
    parsed_answer: str | None = None
    parsed_analysis: str | None = None
    question_hash: str | None = None
    duplicate_status: str | None = "normal"
    duplicate_of_question_id: int | None = None
    duplicate_of_import_id: int | None = None
    status: str
    review_note: str | None = None
    question_id: int | None = None
    reject_reason: str | None = None
    reviewed_by: int | None = None
    reviewed_at: datetime | None = None
    ai_generated: bool
    ai_source: str | None = None
    ai_confidence: float | None = None
    ai_metadata: dict | None = None
    ai_reviewed_at: datetime | None = None
    ai_answer_flag: bool
    created_at: datetime
    updated_at: datetime


class AdminImportBatchDetail(AdminImportBatchListItem):
    items: list[AdminImportQuestionItem]
    page: int
    page_size: int
    total_pages: int


class AdminImportEnrichResponse(BaseModel):
    task_id: str
    batch_id: str
    status: str
    created_at: datetime


class AdminImportQuestionUpdateRequest(BaseModel):
    subject: str | None = None
    question_type: str | None = None
    stem: str | None = None
    options: list[dict] | dict | None = None
    answer: str | None = None
    analysis: str | None = None
    parsed_content: dict | None = None
    parsed_options: dict | None = None
    parsed_answer: str | None = None
    parsed_analysis: str | None = None
    raw_data: dict | None = None
    review_note: str | None = None


class AdminImportRejectRequest(BaseModel):
    reason: str | None = None


class AdminImportActionResponse(BaseModel):
    id: int | None = None
    batch_id: str | None = None
    status: str
    affected_count: int = 0


class AdminImportDeleteResponse(BaseModel):
    batch_id: str | None = None
    id: int | None = None
    deleted_count: int


class AdminImportTaskStatusResponse(BaseModel):
    task_id: str
    batch_id: str
    status: str
    created_at: str | datetime
    updated_at: str | datetime | None = None
    total_count: int | None = None
    processed_count: int | None = None
    error_message: str | None = None
