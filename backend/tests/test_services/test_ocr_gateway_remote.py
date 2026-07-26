"""Test OCRGateway integration with remote (paddlex_http) worker client.

All tests use mock HTTP transport — no real Windows service.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from app.core.deployment_profile import DeploymentProfile
from app.core.ocr_runtime_config import OcrRuntimeConfig
from app.features.ocr_gateway import OCRGateway
from app.services.ocr_worker_client import create_ocr_worker_client

_FAKE_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


def _make_response(
    rec_texts: list[str] | None = None,
    rec_scores: list[float] | None = None,
) -> dict:
    return {
        "logId": "t",
        "errorCode": 0,
        "errorMsg": "Success",
        "result": {
            "ocrResults": [{
                "prunedResult": {
                    "rec_texts": rec_texts or ["ok"],
                    "rec_scores": rec_scores or [0.95],
                    "rec_polys": [[[0, 0], [10, 0], [10, 10], [0, 10]]],
                    "rec_boxes": [[0, 0, 10, 10]],
                }
            }]
        },
    }


@pytest.fixture
def mock_transport():
    return httpx.MockTransport(lambda r: httpx.Response(200, json=_make_response()))


class TestGatewayWithRemoteClient:
    """OCRGateway wired to a PaddleXHttpOcrWorkerClient."""

    @pytest.mark.asyncio
    async def test_recognize_pages_success(self, mock_transport):
        cfg = OcrRuntimeConfig(
            execution_backend="paddlex_http",
            remote_url="http://127.0.0.1:8080/ocr",
        )
        client = create_ocr_worker_client(cfg)
        assert client is not None
        # Override with mock transport
        client._client = httpx.AsyncClient(transport=mock_transport)

        gateway = OCRGateway(mode="gateway", profile=DeploymentProfile.CLOUD_API, worker_client=client)
        results = await gateway.recognize_pages([(0, _FAKE_PNG), (2, _FAKE_PNG)])
        await gateway.shutdown()

        assert len(results) == 2
        assert results[0].page_index == 0
        assert results[1].page_index == 2
        assert all(r.status == "success" for r in results)

    @pytest.mark.asyncio
    async def test_gateway_shutdown_idempotent(self, mock_transport):
        cfg = OcrRuntimeConfig(
            execution_backend="paddlex_http",
            remote_url="http://127.0.0.1:8080/ocr",
        )
        client = create_ocr_worker_client(cfg)
        client._client = httpx.AsyncClient(transport=mock_transport)

        gateway = OCRGateway(mode="gateway", profile=DeploymentProfile.CLOUD_API, worker_client=client)
        await gateway.shutdown()
        await gateway.shutdown()  # second call must not raise

    @pytest.mark.asyncio
    async def test_worker_metrics(self, mock_transport):
        cfg = OcrRuntimeConfig(
            execution_backend="paddlex_http",
            remote_url="http://127.0.0.1:8080/ocr",
        )
        client = create_ocr_worker_client(cfg)
        client._client = httpx.AsyncClient(transport=mock_transport)

        gateway = OCRGateway(mode="gateway", profile=DeploymentProfile.CLOUD_API, worker_client=client)
        await gateway.recognize_pages([(0, _FAKE_PNG)])
        await gateway.shutdown()

        m = gateway.worker_metrics
        assert m["accepted"] >= 1
        assert m["finished"] >= 1
        assert m["backend"] == "paddlex_http"

    @pytest.mark.asyncio
    async def test_remote_failure_fail_closed(self):
        """Remote failure must not trigger local process fallback."""
        transport = httpx.MockTransport(lambda r: httpx.Response(500, text="fail"))
        cfg = OcrRuntimeConfig(
            execution_backend="paddlex_http",
            remote_url="http://127.0.0.1:8080/ocr",
            environment="development",
            unsafe_thread_fallback_enabled=True,
        )
        client = create_ocr_worker_client(cfg)
        client._client = httpx.AsyncClient(transport=transport)

        gateway = OCRGateway(mode="gateway", profile=DeploymentProfile.CLOUD_API, worker_client=client)
        results = await gateway.recognize_pages([(0, _FAKE_PNG)])
        await gateway.shutdown()

        assert len(results) == 1
        assert results[0].status == "failed"

    @pytest.mark.asyncio
    async def test_paddlex_http_ignores_thread_fallback(self, mock_transport):
        """paddlex_http with unsafe_thread_fallback must warn and NOT enter local OCR."""
        import logging
        from app.core.ocr_runtime_config import OcrRuntimeConfig

        cfg = OcrRuntimeConfig(
            execution_backend="paddlex_http",
            remote_url="http://127.0.0.1:8080/ocr",
            environment="development",
            unsafe_thread_fallback_enabled=True,
        )
        client = create_ocr_worker_client(cfg)
        client._client = httpx.AsyncClient(transport=mock_transport)

        # Simulate misconfiguration: worker_client is None but thread fallback is on
        gateway = OCRGateway(mode="gateway", profile=DeploymentProfile.CLOUD_API, worker_client=None)
        gateway._get_runtime_config = lambda: cfg

        # When worker_client is None, the Gateway tries to init it via factory.
        # Since the factory succeeds, we won't reach the thread fallback path.
        # But we can verify the factory does create a paddlex client.
        # Test that the Gateway can handle the None client gracefully.
        # Override _init_worker_client to return None to simulate failure
        original_init = gateway._init_worker_client
        gateway._init_worker_client = lambda: None

        results = await gateway.recognize_pages([(0, _FAKE_PNG)])
        await gateway.shutdown()

        assert len(results) == 1
        # Should fail with ENGINE_NOT_AVAILABLE, not legacy OCR
        assert results[0].stable_error_code == "ocr.engine_not_available"
