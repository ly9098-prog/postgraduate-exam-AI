from app.schemas.base import BaseModel


class SyncManifest(BaseModel):
    question_count: int
    tag_count: int
    checksum: str = ""


class SyncPackage(BaseModel):
    version: int = 1
    exported_at: str
    source_env: str = "local"
    questions: list[dict]
    tags: list[dict]
    manifest: SyncManifest


class SyncReportResponse(BaseModel):
    success: bool
    questions_new: int = 0
    questions_updated: int = 0
    questions_skipped: int = 0
    questions_conflict: int = 0
    questions_deduped: int = 0
    tags_new: int = 0
    tags_skipped: int = 0
    conflicts: list[dict] = []
    errors: list[str] = []
