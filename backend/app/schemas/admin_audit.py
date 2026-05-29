from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


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


class AdminAuditLogDetail(AdminAuditLogListItem):
    detail: dict[str, Any] | None = None
    user_agent: str | None = None
    error_message: str | None = None
