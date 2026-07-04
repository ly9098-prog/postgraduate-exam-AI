from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, field_serializer

from app.core.time_utils import serialize_utc_datetime


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


class AdminAuditLogDetail(AdminAuditLogListItem):
    detail: dict[str, Any] | None = None
    user_agent: str | None = None
