"""Test OcrWorkerClient factory and Protocol."""
from __future__ import annotations

import pytest

from app.core.ocr_runtime_config import OcrRuntimeConfig
from app.services.ocr_worker_client import (
    OcrWorkerClient,
    create_ocr_worker_client,
)


class TestFactory:
    """Tests for ``create_ocr_worker_client``."""

    def test_disabled_returns_none(self):
        cfg = OcrRuntimeConfig(execution_backend="disabled")
        client = create_ocr_worker_client(cfg)
        assert client is None

    def test_paddlex_http_creates_client(self):
        cfg = OcrRuntimeConfig(
            execution_backend="paddlex_http",
            remote_url="http://127.0.0.1:8080/ocr",
        )
        client = create_ocr_worker_client(cfg)
        assert client is not None
        assert isinstance(client, OcrWorkerClient)
        # Check it's the right concrete type
        from app.services.ocr_paddlex_http_client import PaddleXHttpOcrWorkerClient
        assert isinstance(client, PaddleXHttpOcrWorkerClient)

    def test_invalid_backend_raises(self):
        cfg = OcrRuntimeConfig(execution_backend="nonexistent")
        with pytest.raises(ValueError, match="execution_backend"):
            create_ocr_worker_client(cfg)

    def test_shutdown_paddlex_client(self):
        cfg = OcrRuntimeConfig(
            execution_backend="paddlex_http",
            remote_url="http://127.0.0.1:8080/ocr",
        )
        client = create_ocr_worker_client(cfg)
        # Shutdown should be idempotent and not raise
        import asyncio
        asyncio.run(client.shutdown())
        asyncio.run(client.shutdown())  # second call must be OK


class TestOcrWorkerClientProtocol:
    """Check that ``PaddleXHttpOcrWorkerClient`` satisfies the protocol."""

    def test_is_runtime_checkable(self):
        cfg = OcrRuntimeConfig(
            execution_backend="paddlex_http",
            remote_url="http://127.0.0.1:8080/ocr",
        )
        from app.services.ocr_paddlex_http_client import PaddleXHttpOcrWorkerClient
        client = PaddleXHttpOcrWorkerClient(cfg)
        assert isinstance(client, OcrWorkerClient)

    def test_has_required_methods(self):
        cfg = OcrRuntimeConfig(
            execution_backend="paddlex_http",
            remote_url="http://127.0.0.1:8080/ocr",
        )
        from app.services.ocr_paddlex_http_client import PaddleXHttpOcrWorkerClient
        client = PaddleXHttpOcrWorkerClient(cfg)
        assert hasattr(client, "recognize")
        assert hasattr(client, "recognize_batch")
        assert hasattr(client, "shutdown")
        assert hasattr(client, "metrics")
        assert callable(client.recognize)
        assert callable(client.recognize_batch)
        assert callable(client.shutdown)
