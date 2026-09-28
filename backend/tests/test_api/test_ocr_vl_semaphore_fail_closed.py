"""PaddleOCR-VL distributed semaphore must fail closed in restricted envs."""

from unittest.mock import AsyncMock, patch

import pytest

from app.features.ocr_vl.paddleocr_vl_client import (
    JobSubmissionError,
    PaddleOCRVLClient,
)

pytestmark = pytest.mark.asyncio


def _client() -> PaddleOCRVLClient:
    return PaddleOCRVLClient(api_token="test-token")


@patch("app.features.ocr_vl.paddleocr_vl_client._OCR_VL_SEM_KEY", "semaphore:test")
async def test_restricted_env_raises_when_redis_unavailable():
    client = _client()
    with (
        patch.object(PaddleOCRVLClient, "_restricted", return_value=True),
        patch("app.core.cache.cache._ensure_client", new=AsyncMock(return_value=None)),
    ):
        with pytest.raises(JobSubmissionError):
            await client._acquire_semaphore()


@patch("app.features.ocr_vl.paddleocr_vl_client._OCR_VL_SEM_KEY", "semaphore:test")
async def test_restricted_env_raises_on_redis_error():
    client = _client()
    fake_redis = AsyncMock()
    fake_redis.eval = AsyncMock(side_effect=RuntimeError("redis down"))
    with (
        patch.object(PaddleOCRVLClient, "_restricted", return_value=True),
        patch(
            "app.core.cache.cache._ensure_client",
            new=AsyncMock(return_value=fake_redis),
        ),
    ):
        with pytest.raises(JobSubmissionError):
            await client._acquire_semaphore()


@patch("app.features.ocr_vl.paddleocr_vl_client._OCR_VL_SEM_KEY", "semaphore:test")
async def test_local_env_degrades_when_redis_unavailable():
    client = _client()
    with (
        patch.object(PaddleOCRVLClient, "_restricted", return_value=False),
        patch("app.core.cache.cache._ensure_client", new=AsyncMock(return_value=None)),
    ):
        assert await client._acquire_semaphore() is None


@patch("app.features.ocr_vl.paddleocr_vl_client._OCR_VL_SEM_KEY", "semaphore:test")
async def test_capacity_full_returns_false():
    client = _client()
    fake_redis = AsyncMock()
    fake_redis.eval = AsyncMock(return_value=0)
    with (
        patch.object(PaddleOCRVLClient, "_restricted", return_value=True),
        patch(
            "app.core.cache.cache._ensure_client",
            new=AsyncMock(return_value=fake_redis),
        ),
    ):
        assert await client._acquire_semaphore() is False
