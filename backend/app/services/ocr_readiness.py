"""OCR readiness checks with explicit configuration and failure state."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import Settings


@dataclass
class OcrReadinessState:
    consecutive_failures: int = 0


def _ocr_config_issues(settings: "Settings", exec_backend: str) -> list[str]:
    issues: list[str] = []

    # Check for local paddle in sys.modules under cloud → immediate unavailable
    if exec_backend == "local_process":
        issues.append("local_process backend not allowed")

    if settings.OCR_USE_GPU is not False:
        issues.append("GPU should be disabled")

    if exec_backend == "paddlex_http" and not settings.OCR_REMOTE_TOKEN:
        issues.append("remote token not set")

    return issues


async def check_ocr_config(settings: "Settings", state: OcrReadinessState) -> str | None:
    """Check OCR configuration. Returns status string or None if not applicable.

    Returns "ok", "degraded", "unavailable", or None (no OCR configured).

    Config errors → immediate "unavailable" in cloud/production, "degraded" in dev.
    Remote connectivity errors → hysteresis: 3 consecutive failures → "degraded".
    Local paddle modules in cloud → "unavailable".
    """
    if not settings.OCR_ENABLED:
        return None

    exec_backend = (settings.OCR_EXECUTION_BACKEND or "").lower()
    issues = _ocr_config_issues(settings, exec_backend)
    from app.core.ocr_isolation import (
        is_restricted_ocr_environment,
        loaded_local_ocr_modules,
    )

    is_cloud = is_restricted_ocr_environment()

    # Local paddle in sys.modules under cloud → unavailable
    if is_cloud and loaded_local_ocr_modules():
        issues.append("local paddle modules loaded in cloud deployment")

    if issues:
        if is_cloud:
            return "unavailable"
        return "degraded"

    # Remote connectivity check with hysteresis (only for remote backends)
    if exec_backend == "paddlex_http":
        remote_ok = await check_ocr_remote_connectivity(settings)
        if remote_ok:
            state.consecutive_failures = 0
            return "ok"
        else:
            state.consecutive_failures += 1
            if state.consecutive_failures >= 3:
                return "degraded"
            # Transient failure — still ok until threshold
            return "ok"

    return "ok"


async def check_ocr_remote_connectivity(settings: "Settings") -> bool:
    """Lightweight health check against remote OCR endpoint.

    Returns True if reachable, False on any failure.
    Does NOT update hysteresis counters — caller is responsible.
    """
    if not settings.OCR_ENABLED:
        return True
    exec_backend = (settings.OCR_EXECUTION_BACKEND or "").lower()
    if exec_backend != "paddlex_http" or not settings.OCR_REMOTE_URL:
        return True
    try:
        import httpx

        url = settings.OCR_REMOTE_URL
        timeout = httpx.Timeout(settings.OCR_REMOTE_HEALTH_TIMEOUT_SEC)
        from app.core.log_context import get_trace_headers

        headers = get_trace_headers()
        if settings.OCR_REMOTE_TOKEN:
            header_name = getattr(settings, "OCR_REMOTE_AUTH_HEADER", "Authorization")
            scheme = getattr(settings, "OCR_REMOTE_AUTH_SCHEME", "Bearer")
            headers[header_name] = f"{scheme} {settings.OCR_REMOTE_TOKEN}"
        async with httpx.AsyncClient(timeout=timeout) as client:
            respiratory = url.rstrip("/") + "/health"
            resp = await client.get(respiratory, headers=headers)
            return resp.status_code < 500
    except Exception:
        return False
