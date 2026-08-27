from app.schemas.base import BaseModel
import re
from datetime import datetime
from typing import Any, Literal

from pydantic import (
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

_IMAGE_TARGET_RE = re.compile(r"option:[A-Z]")


def validate_image_target(v: str) -> str:
    """Validate an image target: "stem" or "option:A"-"option:Z"."""
    if v != "stem" and not _IMAGE_TARGET_RE.fullmatch(v):
        raise ValueError("target 必须是 'stem' 或 'option:A'-'option:Z'")
    return v

from app.features.question_type import validate_question_type


class AdminQuestionImportSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    batch_id: str
    source_type: str
    source_file: str | None = None
    subject: str | None = None
    subject_id: int | None = None
    question_type: str | None = None
    raw_data: dict[str, Any]
    parsed_content: dict[str, Any] | None = None
    parsed_options: dict[str, Any] | None = None
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
    created_at: datetime
    updated_at: datetime


class AdminQuestionListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    subject_id: int | None = None
    subject_code: str | None = None
    subject_name: str | None = None
    subject_path: str | None = None
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

    @model_validator(mode="before")
    @classmethod
    def _fill_subject_display(cls, data):
        if hasattr(data, "subject_ref"):
            ref = data.subject_ref
            if ref:
                if isinstance(data, dict):
                    data.setdefault("subject_code", ref.code)
                    data.setdefault("subject_name", ref.name)
                    data.setdefault("subject_path", ref.path)
                else:
                    # ORM object — Pydantic from_attributes will pick up computed fields
                    pass
        return data


class AdminQuestionDetail(AdminQuestionListItem):
    import_record: AdminQuestionImportSummary | None = None


class AdminQuestionPatchRequest(BaseModel):
    subject_id: int | None = None
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

    @field_validator("question_type")
    @classmethod
    def _validate_type(cls, v: str | None) -> str | None:
        if v is not None:
            validate_question_type(v)
        return v

    @model_validator(mode="after")
    def require_edit_field(self):
        data = self.model_dump(exclude_unset=True)
        if not any(field != "edit_reason" for field in data):
            raise ValueError("至少提供一个编辑字段")
        return self


class AdminQuestionToggleActiveRequest(BaseModel):
    is_active: bool


class AdminQuestionBatchRequest(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=50)


class AdminQuestionExportRequest(BaseModel):
    format: Literal["csv", "docx"] = "csv"
    ids: list[int] | None = Field(default=None, max_length=5000)
    subject_id: int | None = None
    review_status: str | None = None
    is_active: bool | None = None
    question_type: str | None = Field(default=None, max_length=32)
    keyword: str | None = Field(default=None, max_length=200)
    year: int | None = None
    import_batch_id: str | None = Field(default=None, max_length=64)
    difficulty: int | None = Field(default=None, ge=1, le=5)

    @field_validator("question_type")
    @classmethod
    def _validate_export_question_type(cls, v: str | None) -> str | None:
        if v:
            validate_question_type(v)
        return v

    @field_validator("ids")
    @classmethod
    def _validate_export_ids(cls, v: list[int] | None) -> list[int] | None:
        if v is None:
            return None
        normalized = list(dict.fromkeys(v))
        if any(item <= 0 for item in normalized):
            raise ValueError("ids 必须是正整数")
        return normalized


class AdminQuestionBatchFailure(BaseModel):
    id: int
    error: str


class AdminQuestionBatchResult(BaseModel):
    success_ids: list[int]
    failed_items: list[AdminQuestionBatchFailure]

    @computed_field
    @property
    def successIds(self) -> list[int]:  # noqa: N802
        return self.success_ids

    @computed_field
    @property
    def failedItems(self) -> list[AdminQuestionBatchFailure]:  # noqa: N802
        return self.failed_items

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class AdminQuestionVersionListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    question_id: int
    version: int
    edited_by: int
    edited_by_name: str | None = None
    edit_reason: str | None = None
    created_at: datetime


class AdminQuestionVersionDetail(AdminQuestionVersionListItem):
    content: dict[str, Any]
    options: dict[str, Any] | None = None
    answer: str
    analysis: str | None = None
    difficulty: int
    knowledge_points: list[str] = Field(default_factory=list)


class AdminQuestionAddOptionItem(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    key: str | None = Field(default=None, max_length=1)

    @field_validator("key")
    @classmethod
    def _validate_key(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.upper()
        if not re.fullmatch(r"[A-Z]", v):
            raise ValueError("key 必须是 A-Z 的单个字母")
        return v


class AdminQuestionAddOptionsRequest(BaseModel):
    options: list[AdminQuestionAddOptionItem] = Field(min_length=1, max_length=26)
    edit_reason: str | None = Field(default=None, max_length=256)


class AdminQuestionDeleteImageRequest(BaseModel):
    target: str
    url: str
    edit_reason: str | None = Field(default=None, max_length=256)

    @field_validator("target")
    @classmethod
    def _validate_target(cls, v: str) -> str:
        return validate_image_target(v)
