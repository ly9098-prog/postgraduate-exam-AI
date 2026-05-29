from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AdminSubjectCreateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=64)
    parent_id: int | None = None
    sort_order: int = 0
    is_active: bool = True


class AdminSubjectUpdateRequest(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=32)
    name: str | None = Field(default=None, min_length=1, max_length=64)
    parent_id: int | None = None
    sort_order: int | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def require_update_field(self):
        if not self.model_dump(exclude_unset=True):
            raise ValueError("至少提供一个更新字段")
        return self


class AdminSubjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    parent_id: int | None = None
    code: str
    name: str
    level: int
    path: str
    sort_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class AdminSubjectTreeNode(AdminSubjectResponse):
    children: list[AdminSubjectTreeNode] = Field(default_factory=list)
