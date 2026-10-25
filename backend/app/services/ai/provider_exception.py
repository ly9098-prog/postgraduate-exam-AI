"""Classify AI provider failures into stable API/retry semantics."""

from __future__ import annotations

import re


def classify_ai_provider_exception(
    exc: Exception, *, visual: bool
) -> tuple[str, bool, str]:
    """Map provider/client failures without exposing response bodies."""
    text = str(exc or "").lower()
    error_kind = str(getattr(exc, "error_kind", "") or "")
    typed_retryable = getattr(exc, "retryable", None)
    status = _typed_status(exc, text)

    if (
        error_kind == "auth"
        or status in {401, 403}
        or _contains_any(
            text,
            (
                "invalid_api_key",
                "invalid api-key",
                "authentication",
                "unauthorized",
                "forbidden",
            ),
        )
    ):
        return "ai_provider_auth_failed", False, "fallback"

    if (
        error_kind == "rate_limit"
        or status == 429
        or _contains_any(
            text,
            ("rate limit", "rate_limit", "too many requests", "quota"),
        )
    ):
        return "ai_provider_rate_limited", True, "fallback"

    if (
        error_kind == "transient"
        or status in {408, 425, 500, 502, 503, 504}
        or _contains_any(
            text,
            (
                "timeout",
                "timed out",
                "temporarily unavailable",
                "connection reset",
                "connection error",
            ),
        )
    ):
        return "ai_provider_transient", True, "fallback"

    if error_kind == "model_not_found":
        return "ai_provider_model_not_found", False, "fallback"

    if error_kind in {"parameter_unsupported", "invalid_request"}:
        return "ai_provider_request_incompatible", False, "fallback"

    if _looks_like_vision_rejection(text, error_kind, visual):
        return "vision_unavailable", False, "vision_unavailable"

    # Preserve a typed client's retryability decision instead of retrying a
    # deterministic 4xx forever.
    retryable = True if typed_retryable is None else bool(typed_retryable)
    return "ai_provider_error", retryable, "fallback"


def _typed_status(exc: Exception, text: str) -> int | None:
    raw = getattr(exc, "status_code", None)
    try:
        status = int(raw) if raw is not None else None
    except (TypeError, ValueError):
        status = None
    if status is not None:
        return status
    match = re.search(
        r"(?:api error:|status(?:_code)?[=: ]+)\s*(\d{3})", text
    )
    return int(match.group(1)) if match else None


def _contains_any(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token in text for token in tokens)


def _looks_like_vision_rejection(
    text: str, error_kind: str, visual: bool
) -> bool:
    return visual and (
        error_kind == "vision_unsupported"
        or _contains_any(
            text,
            ("image", "vision", "multimodal", "image_url", "content type"),
        )
    )
