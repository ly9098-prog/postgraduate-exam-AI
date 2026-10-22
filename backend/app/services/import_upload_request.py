"""Validated-by-entry upload inputs shared by format-specific admission paths."""

from dataclasses import dataclass


@dataclass(frozen=True)
class UploadRequest:
    file_path: str
    filename: str
    content_type: str | None
    subject: str | None = None
    subject_id: int | None = None
    import_mode: str = "auto"
    enable_ai_repair: bool = True
    confidence_threshold: float = 0.6
    image_fast_mode: bool = True
    page_start: int | None = None
    page_end: int | None = None
    created_by: str | None = None
    source_sha256: str | None = None
