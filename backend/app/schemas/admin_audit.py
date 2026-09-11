from datetime import datetime
from typing import Any, Literal

from pydantic import ConfigDict, field_serializer

from app.core.time_utils import serialize_utc_datetime
from app.schemas.base import BaseModel


class AdminAuditLogListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    operator_id: int | None = None
    operator_name: str | None = None
    action: str
    resource_type: str | None = None
    resource_id: str | None = None
    severity: str
    status: str
    ip: str | None = None
    created_at: datetime
    detail_summary: dict[str, Any] | None = None
    error_message: str | None = None

    @field_serializer("created_at")
    @classmethod
    def serialize_dt(cls, value: datetime) -> str:
        return serialize_utc_datetime(value)


class QuestionAuditDetail(BaseModel):
    """Unified question detail extracted from audit log or current database."""

    id: int | None = None
    subject_id: int | None = None
    subject_code: str | None = None
    subject_name: str | None = None
    question_type: str | None = None
    content: Any | None = None
    content_text: str | None = None
    content_preview: str | None = None
    options: Any | None = None
    answer: Any | None = None
    analysis: Any | None = None
    knowledge_points: Any | None = None
    difficulty: Any | None = None
    source: str | None = None
    source_type: str | None = None
    source_file: str | None = None
    year: int | None = None
    review_status: str | None = None
    is_active: bool | None = None
    data_source: (
        Literal[
            "audit_snapshot",
            "audit_before",
            "audit_after",
            "audit_summary",
            "current_database",
        ]
        | None
    ) = None


class AdminAuditLogDetail(AdminAuditLogListItem):
    detail: dict[str, Any] | None = None
    user_agent: str | None = None
    question_detail: QuestionAuditDetail | None = None
