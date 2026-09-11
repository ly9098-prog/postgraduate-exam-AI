"""Legacy re-export — use ``app.core.resource_guard`` instead."""

from app.core.resource_guard import (  # noqa: F401
    ARTIFACT_SIZE_LIMIT_EXCEEDED,
    CONCURRENCY_LIMIT_EXCEEDED,
    INPUT_TOO_LARGE,
    PAGE_LIMIT_EXCEEDED,
    PAGE_TIMEOUT,
    PIPELINE_TIMEOUT,
    PIXEL_BUDGET_EXCEEDED,
    REMOTE_OCR_CALL_BUDGET_EXCEEDED,
    RESOURCE_PRESSURE,
    ResourceGuard,
    ResourceGuardError,
)
