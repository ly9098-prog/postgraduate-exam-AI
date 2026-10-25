"""Compatibility baseline for AI provider exception classification."""

from __future__ import annotations

import pytest

from app.services.ai.provider_exception import classify_ai_provider_exception


class TypedException(Exception):
    def __init__(self, message, *, status_code=None, error_kind="", retryable=None):
        super().__init__(message)
        self.status_code = status_code
        self.error_kind = error_kind
        self.retryable = retryable


@pytest.mark.parametrize(
    ("exc", "visual", "expected"),
    [
        (TypedException("invalid_api_key"), False, "ai_provider_auth_failed"),
        (TypedException("authentication failed"), False, "ai_provider_auth_failed"),
        (TypedException("failed", status_code=403), False, "ai_provider_auth_failed"),
        (TypedException("quota exceeded"), False, "ai_provider_rate_limited"),
        (TypedException("failed", status_code=429), False, "ai_provider_rate_limited"),
        (TypedException("connection reset"), False, "ai_provider_transient"),
        (TypedException("failed", status_code=503), False, "ai_provider_transient"),
        (
            TypedException("failed", error_kind="model_not_found"),
            False,
            "ai_provider_model_not_found",
        ),
        (
            TypedException("failed", error_kind="invalid_request"),
            False,
            "ai_provider_request_incompatible",
        ),
        (TypedException("image content type rejected"), True, "vision_unavailable"),
        (TypedException("image content type rejected"), False, "ai_provider_error"),
        (TypedException("unknown transport"), False, "ai_provider_error"),
        (TypedException("API Error: 404"), False, "ai_provider_error"),
    ],
)
def test_stable_error_codes(exc, visual, expected):
    code, _retryable, _model = classify_ai_provider_exception(exc, visual=visual)
    assert code == expected


def test_typed_retryability_is_preserved():
    assert classify_ai_provider_exception(
        TypedException("unknown", retryable=False), visual=False
    ) == ("ai_provider_error", False, "fallback")
    assert classify_ai_provider_exception(
        TypedException("unknown", retryable=True), visual=False
    ) == ("ai_provider_error", True, "fallback")


def test_invalid_typed_status_falls_back_to_message():
    assert classify_ai_provider_exception(
        TypedException("status_code=502", status_code="invalid"), visual=False
    ) == ("ai_provider_transient", True, "fallback")
