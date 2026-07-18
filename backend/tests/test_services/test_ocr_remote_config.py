"""Test OCR remote execution backend configuration."""
from __future__ import annotations

import pytest
from app.core.ocr_runtime_config import (
    OcrRuntimeConfig,
    sanitize_url,
    _validate_config,
)


class TestSanitizeUrl:
    def test_clean_url_unchanged(self):
        assert sanitize_url("http://127.0.0.1:8080/ocr") == "http://127.0.0.1:8080/ocr"

    def test_credentials_stripped(self):
        result = sanitize_url("http://user:pass@host:8080/ocr")
        assert "user" not in result
        assert "pass" not in result
        assert result == "http://host:8080/ocr"

    def test_query_string_stripped(self):
        result = sanitize_url("http://host:8080/ocr?token=abc123")
        assert "token" not in result
        assert "abc123" not in result
        assert result == "http://host:8080/ocr"

    def test_creds_and_query_stripped(self):
        result = sanitize_url("http://admin:secret@host:8080/path?api_key=xyz")
        assert "admin" not in result
        assert "secret" not in result
        assert "api_key" not in result
        assert "host" in result

    def test_empty_string(self):
        assert sanitize_url("") == ""

    def test_malformed_url_fallback(self):
        result = sanitize_url("not a url")
        # Should not crash
        assert isinstance(result, str)


class TestOcrRemoteConfigDefaults:
    """Test that OcrRuntimeConfig carries the expected remote fields."""

    def test_default_execution_backend(self):
        cfg = OcrRuntimeConfig()
        assert cfg.execution_backend == "local_process"

    def test_remote_url_default(self):
        cfg = OcrRuntimeConfig()
        assert isinstance(cfg.remote_url, str)

    def test_remote_timeout_defaults(self):
        cfg = OcrRuntimeConfig()
        assert cfg.remote_connect_timeout_sec == 5.0
        assert cfg.remote_read_timeout_sec == 600.0
        assert cfg.remote_health_timeout_sec == 3.0

    def test_remote_max_concurrency_default(self):
        cfg = OcrRuntimeConfig()
        assert cfg.remote_max_concurrency == 1

    def test_remote_feature_flags_default(self):
        cfg = OcrRuntimeConfig()
        assert cfg.remote_visualize is False
        assert cfg.remote_fail_fast is False
        assert cfg.remote_use_doc_orientation_classify is False
        assert cfg.remote_use_doc_unwarping is False
        assert cfg.remote_use_textline_orientation is False


class TestOcrRemoteConfigValidation:
    """Test _validate_config for remote backend fields."""

    def test_valid_local_process(self):
        cfg = OcrRuntimeConfig(execution_backend="local_process")
        _validate_config(cfg)  # should not raise

    def test_valid_paddlex_http(self):
        cfg = OcrRuntimeConfig(execution_backend="paddlex_http", remote_url="http://host:8080/ocr")
        _validate_config(cfg)  # should not raise

    def test_valid_disabled(self):
        cfg = OcrRuntimeConfig(execution_backend="disabled")
        _validate_config(cfg)  # should not raise

    def test_invalid_backend(self):
        cfg = OcrRuntimeConfig(execution_backend="invalid_backend")
        with pytest.raises(ValueError, match="execution_backend"):
            _validate_config(cfg)

    def test_paddlex_missing_url(self):
        cfg = OcrRuntimeConfig(execution_backend="paddlex_http", remote_url="")
        with pytest.raises(ValueError, match="remote_url"):
            _validate_config(cfg)

    def test_negative_connect_timeout(self):
        cfg = OcrRuntimeConfig(
            execution_backend="paddlex_http",
            remote_url="http://host:8080/ocr",
            remote_connect_timeout_sec=-1,
        )
        with pytest.raises(ValueError, match="remote_connect_timeout_sec"):
            _validate_config(cfg)

    def test_zero_health_timeout(self):
        cfg = OcrRuntimeConfig(
            execution_backend="paddlex_http",
            remote_url="http://host:8080/ocr",
            remote_health_timeout_sec=0,
        )
        with pytest.raises(ValueError, match="remote_health_timeout_sec"):
            _validate_config(cfg)

    def test_zero_max_concurrency(self):
        cfg = OcrRuntimeConfig(
            execution_backend="paddlex_http",
            remote_url="http://host:8080/ocr",
            remote_max_concurrency=0,
        )
        with pytest.raises(ValueError, match="remote_max_concurrency"):
            _validate_config(cfg)

    def test_valid_max_concurrency_one(self):
        cfg = OcrRuntimeConfig(
            execution_backend="paddlex_http",
            remote_url="http://host:8080/ocr",
            remote_max_concurrency=1,
        )
        _validate_config(cfg)  # should not raise
