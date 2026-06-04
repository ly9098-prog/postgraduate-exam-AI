from dataclasses import dataclass, field
from functools import lru_cache

from app.core.config import settings


@dataclass(frozen=True)
class OCRProfile:
    name: str
    use_gpu: bool
    max_workers: int
    timeout_seconds: int
    min_image_width: int
    enable_rotation: bool
    enable_ai_correction: bool
    # 上传限制
    allowed_source_types: tuple[str, ...] = field(default_factory=tuple)
    max_pdf_pages: int = 0  # 0 = 无限制
    max_upload_bytes: int = 10 * 1024 * 1024
    max_batch_files: int = 0  # 0 = 无限制


_LOCAL_PROFILE = OCRProfile(
    name="local",
    use_gpu=True,
    max_workers=4,
    timeout_seconds=1200,
    min_image_width=1500,
    enable_rotation=True,
    enable_ai_correction=True,
    allowed_source_types=("pdf", "excel", "image", "txt"),
    max_pdf_pages=0,
    max_upload_bytes=0,
    max_batch_files=0,
)

_PRODUCTION_PROFILE = OCRProfile(
    name="production",
    use_gpu=False,
    max_workers=2,
    timeout_seconds=300,
    min_image_width=1200,
    enable_rotation=False,
    enable_ai_correction=False,
    allowed_source_types=("pdf", "image", "txt"),
    max_pdf_pages=30,
    max_upload_bytes=5 * 1024 * 1024,
    max_batch_files=1,
)


@lru_cache(maxsize=1)
def get_ocr_profile() -> OCRProfile:
    env = settings.DEPLOY_PROFILE or settings.APP_ENV
    if env in ("local", "development"):
        return _LOCAL_PROFILE
    return _PRODUCTION_PROFILE
