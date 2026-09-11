from datetime import datetime

from app.schemas.base import BaseModel


class TagCreate(BaseModel):
    name: str
    subject_id: int
    parent_id: int | None = None


class TagResponse(BaseModel):
    id: int
    name: str
    subject_id: int
    subject_name: str = ""
    parent_id: int | None = None
    sort_order: int = 0
    created_at: datetime | None = None


class TagTreeNode(BaseModel):
    id: int
    name: str
    children: list["TagTreeNode"] = []


class TagSubjectGroup(BaseModel):
    subject_id: int
    subject_code: str = ""
    subject_name: str = ""
    tags: list[TagResponse]
