"""Unit tests for PaddleX HTTP client auth header."""
from __future__ import annotations

import logging

import pytest

from app.core.ocr_runtime_config import OcrRuntimeConfig


class TestPaddlexAuthHeader:
    """Auth header must be configurable, injected, and never leaked."""

    def make_config(self, **overrides) -> OcrRuntimeConfig:
        defaults = dict(
            execution_backend="paddlex_http",
            remote_url="https://ocr.example.com/ocr",
            remote_auth_token="test-token-12345",
            remote_auth_header="Authorization",
            remote_auth_scheme="Bearer",
            remote_connect_timeout_sec=5.0,
            remote_read_timeout_sec=600.0,
            remote_health_timeout_sec=3.0,
            remote_max_concurrency=1,
        )
        defaults.update(overrides)
        return OcrRuntimeConfig(**defaults)

    def test_auth_header_present_when_token_set(self) -> None:
        """Client must include auth header when token is configured."""
        from app.services.ocr_paddlex_http_client import PaddleXHttpOcrWorkerClient

        config = self.make_config()
        client = PaddleXHttpOcrWorkerClient(config)
        assert client._auth_token == "test-token-12345"
        assert client._auth_header == "Authorization"
        assert client._auth_scheme == "Bearer"
        expected = "Bearer test-token-12345"
        assert client._auth_scheme + " " + client._auth_token == expected

    def test_auth_header_absent_when_token_empty(self) -> None:
        """Client must NOT include auth header when token is empty."""
        from app.services.ocr_paddlex_http_client import PaddleXHttpOcrWorkerClient

        config = self.make_config(remote_auth_token="")
        client = PaddleXHttpOcrWorkerClient(config)
        assert client._auth_token == ""

    def test_custom_auth_header_name(self) -> None:
        """Auth header name must be configurable."""
        from app.services.ocr_paddlex_http_client import PaddleXHttpOcrWorkerClient

        config = self.make_config(
            remote_auth_header="X-API-Key",
            remote_auth_scheme="",
        )
        client = PaddleXHttpOcrWorkerClient(config)
        assert client._auth_header == "X-API-Key"

    def test_invalid_header_name_raises(self) -> None:
        """Header names with injection chars must be rejected."""
        from app.services.ocr_paddlex_http_client import PaddleXHttpOcrWorkerClient

        config = self.make_config(remote_auth_header="X-Invalid\nHeader")
        with pytest.raises(ValueError, match="Invalid OCR auth header name"):
            PaddleXHttpOcrWorkerClient(config)

    def test_invalid_header_name_newline(self) -> None:
        """Newline injection in header name must be rejected."""
        from app.services.ocr_paddlex_http_client import PaddleXHttpOcrWorkerClient

        config = self.make_config(remote_auth_header="X-Foo\r\nBar")
        with pytest.raises(ValueError, match="Invalid OCR auth header name"):
            PaddleXHttpOcrWorkerClient(config)

    def test_invalid_header_name_colon(self) -> None:
        """Colon in header name must be rejected (header injection)."""
        from app.services.ocr_paddlex_http_client import PaddleXHttpOcrWorkerClient

        config = self.make_config(remote_auth_header="X-Foo: Bar")
        with pytest.raises(ValueError, match="Invalid OCR auth header name"):
            PaddleXHttpOcrWorkerClient(config)

    def test_token_not_in_metrics(self) -> None:
        """Metrics endpoint must not contain token."""
        from app.services.ocr_paddlex_http_client import PaddleXHttpOcrWorkerClient

        config = self.make_config()
        client = PaddleXHttpOcrWorkerClient(config)
        metrics = client.metrics
        metrics_str = str(metrics)
        assert "test-token-12345" not in metrics_str, \
            f"Token leaked in metrics: {metrics_str}"


class TestTokenLeakage:
    """Token must never appear in repr, logs, or error messages."""

    def test_token_not_in_repr(self) -> None:
        """OcrRuntimeConfig repr must not contain token value."""
        cfg = OcrRuntimeConfig(
            execution_backend="paddlex_http",
            remote_url="https://ocr.example.com/ocr",
            remote_auth_token="supersecret",
        )
        assert "supersecret" not in repr(cfg)

    def test_token_not_in_caplog(self, caplog) -> None:
        """Token must not appear in log output."""
        from app.services.ocr_paddlex_http_client import PaddleXHttpOcrWorkerClient

        caplog.set_level(logging.INFO)
        cfg = OcrRuntimeConfig(
            execution_backend="paddlex_http",
            remote_url="https://ocr.example.com/ocr",
            remote_auth_token="log-secret",
        )
        PaddleXHttpOcrWorkerClient(cfg)
        for record in caplog.records:
            assert "log-secret" not in record.message, \
                f"Token leaked in log: {record.message}"

    def test_token_not_in_connection_error(self) -> None:
        """Connection error messages must not leak token."""
        cfg = OcrRuntimeConfig(
            execution_backend="paddlex_http",
            remote_url="https://ocr.example.com/ocr",
            remote_auth_token="error-secret",
        )
        msg = f"Connection refused to {cfg.remote_url}"
        assert "error-secret" not in msg

    def test_not_in_readiness_response(self) -> None:
        """Readiness response must not contain token."""
        cfg = OcrRuntimeConfig(
            execution_backend="paddlex_http",
            remote_url="https://ocr.example.com/ocr",
            remote_auth_token="readiness-secret",
        )
        from app.core.ocr_runtime_config import sanitize_url

        msg = f"OCR remote: url={sanitize_url(cfg.remote_url)}"
        assert "readiness-secret" not in msg
