from pydantic import BaseModel


class PublishRequest(BaseModel):
    question_ids: list[int] | None = None
    batch_id: str | None = None


class PublishDetailItem(BaseModel):
    id: int
    status: str  # published / duplicate / failed
    question_id: int | None = None
    reason: str | None = None


class PublishResponse(BaseModel):
    total: int
    published: int
    duplicates: int
    failed: int
    details: list[PublishDetailItem]


class ApproveAndPublishRequest(BaseModel):
    question_ids: list[int]


class ApproveAndPublishResponse(BaseModel):
    total: int
    approved: int
    published: int
    duplicates: int
    failed: int
    details: list[PublishDetailItem]
