"""Readiness Redis probe must not be masked by the in-process cache fallback."""

from unittest.mock import AsyncMock, patch

import pytest

pytestmark = pytest.mark.asyncio


async def test_check_redis_uses_real_ping():
    from app.main import _check_redis

    with (
        patch("app.main.settings") as mock_settings,
        patch("app.core.cache.cache") as mock_cache,
    ):
        mock_settings.REDIS_URL = "redis://localhost:6379/0"
        mock_cache.ping = AsyncMock(return_value=True)
        assert await _check_redis() is True
        mock_cache.ping.assert_awaited_once()
        # The fallback-prone get/set must not be used for the probe.
        mock_cache.set.assert_not_called()
        mock_cache.get.assert_not_called()


async def test_check_redis_reports_failure_when_ping_fails():
    from app.main import _check_redis

    with (
        patch("app.main.settings") as mock_settings,
        patch("app.core.cache.cache") as mock_cache,
    ):
        mock_settings.REDIS_URL = "redis://localhost:6379/0"
        mock_cache.ping = AsyncMock(return_value=False)
        assert await _check_redis() is False


async def test_cache_ping_false_without_redis_url():
    from app.core.cache import CacheClient

    with patch("app.core.cache.settings") as mock_settings:
        mock_settings.REDIS_URL = ""
        client = CacheClient()
        assert await client.ping() is False


async def test_cache_ping_false_when_client_unavailable():
    from app.core.cache import CacheClient

    with patch("app.core.cache.settings") as mock_settings:
        mock_settings.REDIS_URL = "redis://localhost:6379/0"
        client = CacheClient()
        client._ensure_client = AsyncMock(return_value=None)
        assert await client.ping() is False
