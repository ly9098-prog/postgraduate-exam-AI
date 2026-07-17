"""OcrRuntimeConfig — 单一、不可变的 OCR 运行时配置。

统一 `core/config.py`（Settings）和 `core/ocr_profile.py`（OCRProfile）
中的重叠配置项，启动时完成校验，运行时只读。

原则：
- Settings 键优先（env var / .env → 运行时覆盖）
- OCRProfile 退位为环境预设（local / production 默认值）
- 所有最终生效值启动时日志输出
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.core.config import settings
from app.core.ocr_profile import get_ocr_profile

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OcrRuntimeConfig:
    """Immutable, validated runtime config for the OCR pipeline.

    All fields are resolved at construction time from Settings + OCRProfile,
    with Settings taking priority.
    """

    # ── Engine ──
    enabled: bool = False
    use_gpu: bool = False
    language: str = "ch"

    # ── Threading / concurrency ──
    executor_workers: int = 2       # ThreadPoolExecutor max_workers
    max_concurrency: int = 2        # asyncio.Semaphore limit (max simultaneous)
    max_queue_size: int = 10        # max waiting tasks before fast-fail
    task_timeout_seconds: int = 600  # per-task timeout

    # ── Detection params ──
    det_db_thresh: float = 0.2
    det_db_box_thresh: float = 0.4
    det_db_unclip_ratio: float = 1.8
    drop_score: float = 0.3

    # ── Image preprocessing ──
    min_image_width: int = 1500
    enable_rotation: bool = True

    # ── AI correction ──
    enable_ai_correction: bool = True

    # ── Upload / page limits ──
    max_pdf_pages: int = 0          # 0 = no limit
    max_upload_bytes: int = 10 * 1024 * 1024
    max_batch_files: int = 0        # 0 = no limit
    allowed_source_types: tuple[str, ...] = field(
        default_factory=lambda: ("pdf", "excel", "image", "txt"),
    )


def _build_runtime_config() -> OcrRuntimeConfig:
    """Merge Settings + OCRProfile into a single validated config.

    Settings (env vars / .env) take priority over profile defaults.
    """
    profile = get_ocr_profile()

    return OcrRuntimeConfig(
        # Engine
        enabled=settings.OCR_ENABLED,
        use_gpu=settings.OCR_USE_GPU if settings.OCR_USE_GPU is not None else profile.use_gpu,
        language=settings.OCR_LANGUAGE or "ch",

        # Threading / concurrency — Settings take priority
        executor_workers=settings.OCR_EXECUTOR_WORKERS,
        max_concurrency=settings.OCR_MAX_CONCURRENCY,
        max_queue_size=settings.OCR_MAX_QUEUE_SIZE,
        task_timeout_seconds=settings.OCR_TASK_TIMEOUT_SEC,

        # Detection params — from Settings only (no profile overlap)
        det_db_thresh=settings.OCR_DET_DB_THRESH,
        det_db_box_thresh=settings.OCR_DET_DB_BOX_THRESH,
        det_db_unclip_ratio=settings.OCR_DET_DB_UNCLIP_RATIO,
        drop_score=settings.OCR_DROP_SCORE,

        # Image preprocessing — merge Settings over profile
        min_image_width=settings.OCR_MIN_IMAGE_WIDTH or profile.min_image_width,
        enable_rotation=profile.enable_rotation,

        # AI correction — from profile only
        enable_ai_correction=profile.enable_ai_correction,

        # Upload / page limits — from profile
        max_pdf_pages=profile.max_pdf_pages,
        max_upload_bytes=profile.max_upload_bytes,
        max_batch_files=profile.max_batch_files,
        allowed_source_types=profile.allowed_source_types,
    )


# Module-level singleton — built once, never mutated
_runtime_config: OcrRuntimeConfig | None = None


def get_runtime_config() -> OcrRuntimeConfig:
    """Return the process-wide OcrRuntimeConfig singleton.

    Logs the effective config on first access.
    """
    global _runtime_config
    if _runtime_config is None:
        _runtime_config = _build_runtime_config()
        _log_effective_config(_runtime_config)
    return _runtime_config


def _log_effective_config(cfg: OcrRuntimeConfig) -> None:
    """Log the effective OCR runtime configuration (no secrets)."""
    logger.info(
        "OCR runtime config: "
        "enabled=%s use_gpu=%s language=%s "
        "executor_workers=%d max_concurrency=%d max_queue_size=%d "
        "task_timeout=%ds min_image_width=%d rotation=%s ai=%s "
        "max_pages=%d max_upload=%d",
        cfg.enabled, cfg.use_gpu, cfg.language,
        cfg.executor_workers, cfg.max_concurrency, cfg.max_queue_size,
        cfg.task_timeout_seconds, cfg.min_image_width,
        cfg.enable_rotation, cfg.enable_ai_correction,
        cfg.max_pdf_pages, cfg.max_upload_bytes,
    )


def reset_runtime_config() -> None:
    """Reset the runtime config singleton (for testing / config reload)."""
    global _runtime_config
    _runtime_config = None
