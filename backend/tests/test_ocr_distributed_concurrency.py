"""Tests for OcrDistributedConcurrency — Redis ZSET-based global OCR throttling.

Uses fakeredis so no real Redis server is required.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services.ocr_distributed_concurrency import (
    OcrDistributedConcurrency,
    _local_token,
    get_global_concurrency,
    reset_global_concurrency,
)


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_global_concurrency()
    yield
    reset_global_concurrency()


# ---------------------------------------------------------------------------
# Pure token helper
# ---------------------------------------------------------------------------


class TestLocalToken:
    def test_generates_unique(self):
        t1 = _local_token()
        t2 = _local_token()
        assert t1 != t2
        assert t1.startswith("local_")


# ---------------------------------------------------------------------------
# OcrDistributedConcurrency (using fakeredis)
# ---------------------------------------------------------------------------


class TestAcquireRelease:
    """Basic acquire/release lifecycle."""

    @pytest.mark.asyncio
    async def test_acquire_success(self):
        guard = OcrDistributedConcurrency(redis_url="redis://localhost:6379/0")
        # Use fakeredis instead of real redis
        import fakeredis.aioredis as fakeredis_aioredis

        fake_redis = fakeredis_aioredis.FakeRedis(decode_responses=True)
        guard._redis = fake_redis
        from app.services.ocr_distributed_concurrency import _ACQUIRE_LUA, _RELEASE_LUA
        guard._lua_acquire = fake_redis.register_script(_ACQUIRE_LUA)
        guard._lua_release = fake_redis.register_script(_RELEASE_LUA)

        token = await guard.acquire_global(capacity=2, ttl_sec=60)
        assert token is not None
        assert token.startswith("local_")

        count = await guard.current_count()
        assert count == 1

        await guard.close()

    @pytest.mark.asyncio
    async def test_release(self):
        guard = OcrDistributedConcurrency(redis_url="redis://localhost:6379/0")
        import fakeredis.aioredis as fakeredis_aioredis

        fake_redis = fakeredis_aioredis.FakeRedis(decode_responses=True)
        guard._redis = fake_redis
        from app.services.ocr_distributed_concurrency import _ACQUIRE_LUA, _RELEASE_LUA
        guard._lua_acquire = fake_redis.register_script(_ACQUIRE_LUA)
        guard._lua_release = fake_redis.register_script(_RELEASE_LUA)

        token = await guard.acquire_global(capacity=2, ttl_sec=60)
        assert token is not None

        released = await guard.release_global(token)
        assert released is True

        count = await guard.current_count()
        assert count == 0

        await guard.close()

    @pytest.mark.asyncio
    async def test_release_none_token(self):
        """Releasing a None token should be a no-op."""
        guard = OcrDistributedConcurrency(redis_url="redis://localhost:6379/0")
        assert await guard.release_global(None) is True
        assert await guard.release_global("") is True

    @pytest.mark.asyncio
    async def test_capacity_limit(self):
        """When capacity is reached, acquire returns None."""
        guard = OcrDistributedConcurrency(redis_url="redis://localhost:6379/0")
        import fakeredis.aioredis as fakeredis_aioredis

        fake_redis = fakeredis_aioredis.FakeRedis(decode_responses=True)
        guard._redis = fake_redis
        from app.services.ocr_distributed_concurrency import _ACQUIRE_LUA, _RELEASE_LUA
        guard._lua_acquire = fake_redis.register_script(_ACQUIRE_LUA)
        guard._lua_release = fake_redis.register_script(_RELEASE_LUA)

        t1 = await guard.acquire_global(capacity=1, ttl_sec=60)
        assert t1 is not None

        t2 = await guard.acquire_global(capacity=1, ttl_sec=60)
        assert t2 is None, "Should be at capacity"

        await guard.close()


class TestRedisFailure:
    """Fail-closed in production / fail-open in dev."""

    @pytest.mark.asyncio
    async def test_fail_open_non_production(self):
        """When Redis is unreachable in non-production, acquire returns a local token."""
        guard = OcrDistributedConcurrency(redis_url="redis://nonexistent:6379")
        guard._profile = "development"  # Ensure non-production

        with patch.object(guard, '_profile', 'development'):
            token = await guard.acquire_global(capacity=2, ttl_sec=60)
            # In non-production, returns a local token even without Redis
            assert token is not None
            assert token.startswith("local_")

        await guard.close()

    @pytest.mark.asyncio
    async def test_no_redis_url_non_production(self):
        """No REDIS_URL in non-production should log warning and allow."""

        guard = OcrDistributedConcurrency(redis_url="")
        guard._profile = "development"

        with patch.object(guard, '_profile', 'development'):
            token = await guard.acquire_global(capacity=2, ttl_sec=60)
            assert token is not None

        await guard.close()


class TestCount:
    """current_count helper."""

    @pytest.mark.asyncio
    async def test_current_count(self):
        guard = OcrDistributedConcurrency(redis_url="redis://localhost:6379/0")
        import fakeredis.aioredis as fakeredis_aioredis

        fake_redis = fakeredis_aioredis.FakeRedis(decode_responses=True)
        guard._redis = fake_redis
        from app.services.ocr_distributed_concurrency import _ACQUIRE_LUA, _RELEASE_LUA
        guard._lua_acquire = fake_redis.register_script(_ACQUIRE_LUA)
        guard._lua_release = fake_redis.register_script(_RELEASE_LUA)

        count = await guard.current_count()
        assert count == 0

        await guard.acquire_global(capacity=5, ttl_sec=60)
        await guard.acquire_global(capacity=5, ttl_sec=60)
        await guard.acquire_global(capacity=5, ttl_sec=60)

        count = await guard.current_count()
        assert count == 3

        await guard.close()


class TestSingleton:
    """get_global_concurrency singleton."""

    def test_singleton(self):
        g1 = get_global_concurrency()
        g2 = get_global_concurrency()
        assert g1 is g2

    def test_reset(self):
        g1 = get_global_concurrency()
        reset_global_concurrency()
        g2 = get_global_concurrency()
        assert g1 is not g2
