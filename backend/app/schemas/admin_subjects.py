from __future__ import annotations

from datetime import datetime

from pydantic import ConfigDict, Field, computed_field, model_validator

from app.core.subject_scope import EXAM408_ROOT_CODE, canonical_408_code
from app.schemas.base import BaseModel


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
    # Product-safety acknowledgement.  It is consumed by the service layer and
    # never persisted on Subject.  Direct API clients therefore cannot silently
    # disable the 408 root without explicitly acknowledging the impact.
    confirm_core_disable: bool = False

    @model_validator(mode="after")
    def require_update_field(self):
        business_fields = self.model_dump(exclude_unset=True)
        business_fields.pop("confirm_core_disable", None)
        if not business_fields:
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

    @computed_field
    @property
    def product_code(self) -> str | None:
        return canonical_408_code(self.code, self.name)

    @computed_field
    @property
    def product_scope(self) -> str | None:
        return "408" if self.product_code else None

    @computed_field
    @property
    def is_product_core(self) -> bool:
        return self.product_code is not None

    @computed_field
    @property
    def is_product_root(self) -> bool:
        return self.product_code == EXAM408_ROOT_CODE


class AdminSubjectTreeNode(AdminSubjectResponse):
    children: list[AdminSubjectTreeNode] = Field(default_factory=list)
