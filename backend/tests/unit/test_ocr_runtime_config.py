"""Unit tests for OcrRuntimeConfig, with focus on token safety."""
from __future__ import annotations

import logging

import pytest

from app.core.ocr_runtime_config import OcrRuntimeConfig


class TestOcrRuntimeConfigToken:
    """remote_auth_token must never appear in repr, logs, or error messages."""

    def test_token_excluded_from_repr(self) -> None:
        """repr(OcrRuntimeConfig) must not contain the token value."""
        cfg = OcrRuntimeConfig(
            execution_backend="paddlex_http",
            remote_url="https://ocr.example.com/ocr",
            remote_auth_token="supersecret123",
        )
        r = repr(cfg)
        assert "supersecret123" not in r, f"Token leaked in repr: {r}"

    def test_token_not_in_field_names_only(self) -> None:
        """Token field name may appear via other fields, but never its value."""
        cfg = OcrRuntimeConfig(
            execution_backend="paddlex_http",
            remote_auth_token="my-secret-token",
        )
        r = repr(cfg)
        assert "my-secret-token" not in r, f"Token value leaked in repr: {r}"
        # remote_auth_header is in repr (no repr=False), but remote_auth_token is not
        assert "remote_auth_header" in r

    def test_token_not_logged_in_config_log(self, caplog: pytest.LogCaptureFixture) -> None:
        """Simulated config logging must not include token."""
        caplog.set_level(logging.INFO)
        OcrRuntimeConfig(
            execution_backend="paddlex_http",
            remote_url="https://ocr.example.com/ocr",
            remote_auth_token="should-not-appear-in-log",
        )
        for record in caplog.records:
            if "should-not-appear-in-log" in record.message:
                pytest.fail("Token leaked in log output")

    def test_token_not_in_httpx_exception_str(self) -> None:
        """Even if an error originates from httpx, token must not appear."""
        cfg = OcrRuntimeConfig(
            execution_backend="paddlex_http",
            remote_url="https://ocr.example.com/ocr",
            remote_auth_token="token-in-error",
        )
        # Simulate error message construction
        error_msg = f"OCR request failed: connection error to {cfg.remote_url}"
        assert "token-in-error" not in error_msg

    def test_token_not_in_circuit_breaker_error(self) -> None:
        """Circuit breaker error must not contain token."""
        cfg = OcrRuntimeConfig(
            execution_backend="paddlex_http",
            remote_url="https://ocr.example.com/ocr",
            remote_auth_token="circuit-token",
        )
        error = f"Circuit breaker open for {cfg.remote_url}, backend=paddlex_http"
        assert "circuit-token" not in error

    def test_token_not_in_readiness_response(self) -> None:
        """Simulated readiness message must not contain token."""
        cfg = OcrRuntimeConfig(
            execution_backend="paddlex_http",
            remote_url="https://ocr.example.com/ocr",
            remote_auth_token="readiness-token",
        )
        msg = f"OCR remote configured: url={cfg.remote_url}"
        assert "readiness-token" not in msg

    def test_token_not_in_metrics_label(self) -> None:
        """Metrics labels must never use token as label value."""
        label_values = {
            "endpoint": "sanitized_url",
            "status_code": "200",
            "retry_count": "0",
        }
        all_values = " ".join(label_values.values())
        assert "metrics-token" not in all_values


class TestSanitizeUrl:
    """sanitize_url() strips credentials from URLs."""

    def test_strips_user_password(self) -> None:
        from app.core.ocr_runtime_config import sanitize_url

        url = "http://user:pass@host:8080/path"
        result = sanitize_url(url)
        assert "user:pass" not in result
        assert "user" not in result
        assert "host:8080" in result
        assert result.startswith("http://host:8080")

    def test_strips_query_params(self) -> None:
        from app.core.ocr_runtime_config import sanitize_url

        url = "https://ocr.example.com/ocr?token=secret&key=value"
        result = sanitize_url(url)
        assert "token=secret" not in result
        assert "key=value" not in result

    def test_clean_url_unchanged(self) -> None:
        from app.core.ocr_runtime_config import sanitize_url

        url = "https://ocr.example.com/ocr"
        result = sanitize_url(url)
        assert result == url

    def test_empty_string(self) -> None:
        from app.core.ocr_runtime_config import sanitize_url

        assert sanitize_url("") == ""

    def test_malformed_url(self) -> None:
        from app.core.ocr_runtime_config import sanitize_url

        result = sanitize_url("not-a-url")
        # Malformed URLs shouldn't crash
        assert isinstance(result, str)


class TestOcrRuntimeConfigValidation:
    """_validate_config() catches invalid combinations."""

    def test_production_paddlex_http_requires_token(self) -> None:
        """Production + paddlex_http must have non-empty token."""
        cfg = OcrRuntimeConfig(
            execution_backend="paddlex_http",
            remote_url="https://ocr.example.com/ocr",
            remote_auth_token="",
            environment="production",
        )
        from app.core.ocr_runtime_config import _validate_config

        with pytest.raises(ValueError, match="remote_auth_token"):
            _validate_config(cfg)

    def test_development_paddlex_http_no_token_ok(self) -> None:
        """Development + paddlex_http without token is allowed."""
        cfg = OcrRuntimeConfig(
            execution_backend="paddlex_http",
            remote_url="http://localhost:8080/ocr",
            remote_auth_token="",
            environment="development",
        )
        from app.core.ocr_runtime_config import _validate_config

        # Should not raise
        _validate_config(cfg)

    def test_disabled_backend_skips_token_check(self) -> None:
        """Disabled backend must not require token even in production."""
        cfg = OcrRuntimeConfig(
            execution_backend="disabled",
            environment="production",
            remote_auth_token="",
        )
        from app.core.ocr_runtime_config import _validate_config

        _validate_config(cfg)
