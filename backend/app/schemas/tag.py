from datetime import datetime

from pydantic import BaseModel


class TagCreate(BaseModel):
    name: str
    subject: str
    parent_id: int | None = None


class TagResponse(BaseModel):
    id: int
    name: str
    subject: str
    parent_id: int | None = None
    sort_order: int = 0
    created_at: datetime | None = None


class TagTreeNode(BaseModel):
    id: int
    name: str
    children: list["TagTreeNode"] = []


class TagSubjectGroup(BaseModel):
    subject: str
    tags: list[TagResponse]
