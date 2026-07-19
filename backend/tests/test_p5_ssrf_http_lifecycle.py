"""P5: SSRF protection and HTTP lifecycle tests for PaddleOCR-VL client."""

from __future__ import annotations

import socket
from unittest.mock import AsyncMock, patch

import httpx
import pytest


class _MockStreamResponse:
    """A minimal async response mock that supports ``async with`` and ``aiter_bytes``."""

    def __init__(self, status_code=200, content: bytes = b"", url: str = "https://example.com/data", headers: dict | None = None):
        self.status_code = status_code
        self._content = content
        self.url = httpx.URL(url)
        self.headers = headers or {}
        self.text = content.decode("utf-8", errors="replace")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def aiter_bytes(self, chunk_size: int = 8192):
        for i in range(0, len(self._content), chunk_size):
            yield self._content[i:i + chunk_size]


class _MockStreamClient:
    """A minimal async client mock that returns a _MockStreamResponse from ``stream()``.

    ``stream()`` is NOT async — it returns the response directly.
    The calling code uses ``async with client.stream(...) as resp:`` which
    invokes the response's ``__aenter__`` / ``__aexit__``.
    """

    def __init__(self, response: _MockStreamResponse):
        self._response = response

    def stream(self, method, url, **kwargs):
        return self._response

from app.features.ocr_vl.paddleocr_vl_client import (
    JobSubmissionError,
    PaddleOCRVLClient,
    ResultDownloadError,
    _CircuitBreaker,
    CircuitBreakerOpenError,
    _MAX_JSONL_LINES,
    _MAX_RESULT_DOWNLOAD_BYTES,
    _get_retry_after,
    _validate_result_url,
)


class TestSSRFValidation:
    """Verify _validate_result_url rejects unsafe URLs."""

    _UNSAFE_URLS = [
        "http://localhost:8000/secret",
        "http://127.0.0.1:8000/secret",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.1/admin",
        "http://192.168.1.1/config",
        "http://[::1]:8000/",
        "ftp://files.example.com/result.json",
        "file:///etc/passwd",
    ]

    def test_rejects_unsafe_schemes(self):
        for url in self._UNSAFE_URLS:
            with pytest.raises(ResultDownloadError):
                _validate_result_url(url)

    def test_rejects_no_hostname(self):
        with pytest.raises(ResultDownloadError, match="no hostname"):
            _validate_result_url("https:///path")

    def test_accepts_public_url(self):
        url = "https://example.com/results/ocr-output.jsonl"
        try:
            result = _validate_result_url(url)
            assert result == url
        except ResultDownloadError as e:
            if "resolution failed" in str(e):
                pytest.skip("DNS resolution unavailable in this environment")
            raise

    def test_rejects_dns_failure(self):
        with patch("socket.getaddrinfo", side_effect=socket.gaierror("Name or service not known")):
            with pytest.raises(ResultDownloadError, match="resolution failed"):
                _validate_result_url("https://definitely-nonexistent-test.example/result.json")


class TestDownloadValidation:
    """Verify _download_and_parse_jsonl enforces security limits."""

    @pytest.mark.asyncio
    async def test_download_too_large_rejected(self):
        client = PaddleOCRVLClient(api_token="test-token")
        oversized = b"x" * (_MAX_RESULT_DOWNLOAD_BYTES + 1)

        mock_resp = _MockStreamResponse(
            status_code=200, content=oversized,
            url="https://storage.example.com/big.jsonl",
        )

        with patch.object(client, "_get_client") as mock_get_client:
            mock_get_client.return_value = _MockStreamClient(mock_resp)
            with patch(
                "app.features.ocr_vl.paddleocr_vl_client._validate_result_url",
                return_value="https://storage.example.com/big.jsonl",
            ):
                with pytest.raises(ResultDownloadError, match="exceeded"):
                    await client._download_and_parse_jsonl("https://storage.example.com/big.jsonl")

    @pytest.mark.asyncio
    async def test_jsonl_line_limit(self):
        client = PaddleOCRVLClient(api_token="test-token")
        many_lines = "\n".join(['{"idx":' + str(i) + '}' for i in range(_MAX_JSONL_LINES + 1)])

        mock_resp = _MockStreamResponse(
            status_code=200, content=many_lines.encode(),
            url="https://storage.example.com/many.jsonl",
        )

        with patch.object(client, "_get_client") as mock_get_client:
            mock_get_client.return_value = _MockStreamClient(mock_resp)
            with patch(
                "app.features.ocr_vl.paddleocr_vl_client._validate_result_url",
                return_value="https://storage.example.com/many.jsonl",
            ):
                with pytest.raises(ResultDownloadError, match="exceeds limit"):
                    await client._download_and_parse_jsonl("https://storage.example.com/many.jsonl")

    @pytest.mark.asyncio
    async def test_redirect_url_revalidated(self):
        """Final URL after redirect must be re-validated for SSRF safety."""
        client = PaddleOCRVLClient(api_token="test-token")

        entry_validated = False

        def validate_side_effect(url):
            nonlocal entry_validated
            if "169.254" in url or entry_validated:
                raise ResultDownloadError(
                    "Result URL resolves to private/loopback/link-local "
                    "address: 169.254.169.254"
                )
            entry_validated = True
            return url

        # 302 redirect response — follow_redirects=False
        redirect_resp = _MockStreamResponse(
            status_code=302, content=b"",
            url="https://safe.example.com/result.jsonl",
            headers={"location": "http://169.254.169.254/latest/meta-data/"},
        )

        with patch.object(client, "_get_client") as mock_get_client:
            mock_get_client.return_value = _MockStreamClient(redirect_resp)
            with patch(
                "app.features.ocr_vl.paddleocr_vl_client._validate_result_url",
                side_effect=validate_side_effect,
            ):
                with pytest.raises(ResultDownloadError, match="private|loopback|link-local"):
                    await client._download_and_parse_jsonl("https://safe.example.com/result.jsonl")

    @pytest.mark.asyncio
    async def test_download_valid_result(self):
        """Happy path: valid download returns parsed content."""
        client = PaddleOCRVLClient(api_token="test-token")

        jsonl_content = '{"result": {"layoutParsingResults": [{"markdown": {"text": "hello"}}]}}'

        mock_resp = _MockStreamResponse(
            status_code=200, content=jsonl_content.encode(),
            url="https://storage.example.com/result.jsonl",
        )

        with patch.object(client, "_get_client") as mock_get_client:
            mock_get_client.return_value = _MockStreamClient(mock_resp)
            with patch(
                "app.features.ocr_vl.paddleocr_vl_client._validate_result_url",
                return_value="https://storage.example.com/result.jsonl",
            ):
                text, conf, blocks, raw = await client._download_and_parse_jsonl(
                    "https://storage.example.com/result.jsonl"
                )
                assert "hello" in text


class TestRetryAfter:
    """Verify Retry-After is extracted and used correctly."""

    def test_extract_from_response_header(self):
        from unittest.mock import MagicMock
        resp = MagicMock()
        resp.headers = {"Retry-After": "120"}
        assert _get_retry_after(resp) == 120.0
        resp.headers = {"Retry-After": "30"}
        assert _get_retry_after(resp) == 30.0

    def test_missing_retry_after_is_none(self):
        from unittest.mock import MagicMock
        resp = MagicMock()
        resp.headers = {}
        assert _get_retry_after(resp) is None

    @pytest.mark.asyncio
    async def test_retry_after_delays_retry(self):
        client = PaddleOCRVLClient(api_token="test-token", max_retries=2)
        call_count = 0

        async def mock_submit():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise JobSubmissionError(
                    "HTTP 429",
                    status_code=429,
                    retry_after=1.0,
                )
            return "job-id-123"

        job_id = await client._retry_submit(mock_submit, "test")
        assert job_id == "job-id-123"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_non_retriable_4xx_raises(self):
        client = PaddleOCRVLClient(api_token="test-token", max_retries=3)

        async def mock_submit():
            raise JobSubmissionError("HTTP 400: Bad Request")

        with pytest.raises(JobSubmissionError):
            await client._retry_submit(mock_submit, "test")

    @pytest.mark.asyncio
    async def test_retry_exhausted_raises(self):
        client = PaddleOCRVLClient(api_token="test-token", max_retries=2)
        call_count = 0

        async def mock_submit():
            nonlocal call_count
            call_count += 1
            raise JobSubmissionError("HTTP 502: Bad Gateway")

        with pytest.raises(JobSubmissionError, match="All .* attempts failed"):
            await client._retry_submit(mock_submit, "test")
        assert call_count == 2  # used all retries


class TestFromResolver:
    """Verify PaddleOCRVLClient.from_resolver uses AIModelConfigResolver."""

    @pytest.mark.asyncio
    async def test_from_resolver_uses_resolved_config(self):
        """from_resolver should use config from AIModelConfigResolver."""
        from app.services.model_config_resolver import (
            AICapability,
            ResolvedAIModelConfig,
        )

        mock_resolver = AsyncMock()
        mock_resolver.resolve_for_capability = AsyncMock(return_value=ResolvedAIModelConfig(
            config_id="test-config-id",
            model_config_id="test-model-config-id",
            provider="paddleocr-vl",
            model_name="PaddleOCR-VL-1.6",
            endpoint="https://custom.api.example.com",
            timeout_seconds=300.0,
            max_retries=5,
            secret_reference="admin_ai_model_configs.api_key_encrypted",
        ))
        mock_resolver.resolve_secret = AsyncMock(return_value="resolved-secret-token")

        client = await PaddleOCRVLClient.from_resolver(mock_resolver)
        assert client._api_token == "resolved-secret-token"
        assert client._base_url == "https://custom.api.example.com"
        assert client._model == "PaddleOCR-VL-1.6"
        assert client._max_retries == 5

        mock_resolver.resolve_for_capability.assert_called_once_with(AICapability.OCR_VL)
        mock_resolver.resolve_secret.assert_called_once()

    @pytest.mark.asyncio
    async def test_from_resolver_fallback(self):
        """from_resolver should fall back when resolver raises."""
        mock_resolver = AsyncMock()
        mock_resolver.resolve_for_capability = AsyncMock(
            side_effect=ValueError("No config for capability")
        )

        client = await PaddleOCRVLClient.from_resolver(
            mock_resolver,
            fallback_token="fallback-token",
            fallback_base_url="https://fallback.example.com",
        )
        assert client._api_token == "fallback-token"
        assert client._base_url == "https://fallback.example.com"
        assert client._model == "PaddleOCR-VL-1.6"

    @pytest.mark.asyncio
    async def test_from_resolver_logs_fallback(self, caplog):
        """from_resolver should log when falling back to default config."""
        import logging

        caplog.set_level(logging.DEBUG)

        mock_resolver = AsyncMock()
        mock_resolver.resolve_for_capability = AsyncMock(
            side_effect=ImportError("no module")
        )

        client = await PaddleOCRVLClient.from_resolver(mock_resolver)
        assert client._api_token == ""  # no fallback provided
        assert "from_resolver fallback" in caplog.text
