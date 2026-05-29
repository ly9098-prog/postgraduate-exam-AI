from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator


class AdminQuestionImportSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    batch_id: str
    source_type: str
    source_file: str | None = None
    subject: str | None = None
    question_type: str | None = None
    raw_data: dict[str, Any]
    parsed_content: dict[str, Any] | None = None
    parsed_options: dict[str, Any] | None = None
    parsed_answer: str | None = None
    parsed_analysis: str | None = None
    status: str
    review_note: str | None = None
    question_id: int | None = None
    reject_reason: str | None = None
    reviewed_by: int | None = None
    reviewed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class AdminQuestionListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    subject: str
    question_type: str
    content: dict[str, Any]
    options: dict[str, Any] | None = None
    answer: str
    analysis: str | None = None
    knowledge_points: list[Any] | None = None
    difficulty: int
    source: str | None = None
    source_type: str | None = None
    source_file: str | None = None
    import_batch_id: str | None = None
    raw_content: str | None = None
    image_url: list[Any] | None = None
    year: int | None = None
    review_status: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class AdminQuestionDetail(AdminQuestionListItem):
    import_record: AdminQuestionImportSummary | None = None


class AdminQuestionPatchRequest(BaseModel):
    subject: str | None = Field(default=None, max_length=32)
    question_type: str | None = Field(default=None, max_length=32)
    content: dict[str, Any] | None = None
    options: dict[str, Any] | None = None
    answer: str | None = None
    analysis: str | None = None
    knowledge_points: list[Any] | None = None
    difficulty: int | None = Field(default=None, ge=1, le=5)
    source: str | None = Field(default=None, max_length=64)
    source_type: str | None = Field(default=None, max_length=16)
    source_file: str | None = Field(default=None, max_length=256)
    import_batch_id: str | None = Field(default=None, max_length=64)
    raw_content: str | None = None
    image_url: list[Any] | None = None
    year: int | None = None
    edit_reason: str | None = Field(default=None, max_length=256)

    @model_validator(mode="after")
    def require_edit_field(self):
        data = self.model_dump(exclude_unset=True)
        if not any(field != "edit_reason" for field in data):
            raise ValueError("至少提供一个编辑字段")
        return self


class AdminQuestionRejectRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=512)


class AdminQuestionToggleActiveRequest(BaseModel):
    is_active: bool


class AdminQuestionBatchRequest(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=50)


class AdminQuestionBatchRejectRequest(AdminQuestionBatchRequest):
    reason: str = Field(min_length=1, max_length=512)


class AdminQuestionBatchFailure(BaseModel):
    id: int
    error: str


class AdminQuestionBatchResult(BaseModel):
    success_ids: list[int]
    failed_items: list[AdminQuestionBatchFailure]

    @computed_field
    @property
    def successIds(self) -> list[int]:
        return self.success_ids

    @computed_field
    @property
    def failedItems(self) -> list[AdminQuestionBatchFailure]:
        return self.failed_items

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class AdminQuestionVersionListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    question_id: int
    version: int
    edited_by: int
    edit_reason: str | None = None
    created_at: datetime


class AdminQuestionVersionDetail(AdminQuestionVersionListItem):
    content: dict[str, Any]
    options: dict[str, Any] | None = None
    answer: str
    analysis: str | None = None
    difficulty: int
    knowledge_points: Any | None = None
