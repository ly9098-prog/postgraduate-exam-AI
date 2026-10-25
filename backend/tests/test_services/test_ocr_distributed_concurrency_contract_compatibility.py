"""Pure-function compatibility baseline for distributed OCR concurrency contract.

Pins the Redis key name, the four Lua scripts' atomic command sequences, the
token formats, the error type, the constructor's lazy-init state, and the
acquire/release/renew/count decision matrix across development and cloud_api
profiles. The existing ``tests/ocr_pipeline/test_ocr_distributed_concurrency.py``
covers the happy-path lifecycle with fakeredis; this file pins the SCRIPT
CONTRACT and the PROFILE-DEPENDENT FAILURE SEMANTICS so that a later refactor
cannot silently change the Redis key, the atomicity of the Lua operations, the
fail-open/fail-closed boundary, or the best-effort release/renew return values.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.ocr_distributed_concurrency import (
    _ACQUIRE_LUA,
    _COUNT_LUA,
    _OCR_CONCURRENCY_KEY,
    _RELEASE_LUA,
    _RENEW_LUA,
    DistributedConcurrencyError,
    OcrDistributedConcurrency,
    _local_token,
    _redis_token,
)


class TestRedisKey:
    """The ZSET key is a stable protocol contract."""

    def test_key_is_ocr_v2_concurrency(self):
        assert _OCR_CONCURRENCY_KEY == "ocr:v2:concurrency"


class TestAcquireLuaScript:
    """The acquire script is atomic and clock-skew-safe."""

    def test_uses_redis_server_time(self):
        assert 'redis.call("TIME")' in _ACQUIRE_LUA

    def test_removes_expired_entries_before_capacity_check(self):
        # ZREMRANGEBYSCORE must appear before ZCARD in the script
        assert _ACQUIRE_LUA.index("ZREMRANGEBYSCORE") < _ACQUIRE_LUA.index("ZCARD")

    def test_checks_capacity_before_add(self):
        assert _ACQUIRE_LUA.index("ZCARD") < _ACQUIRE_LUA.index("ZADD")

    def test_returns_zero_at_capacity(self):
        assert "if count >= capacity then" in _ACQUIRE_LUA
        assert "return 0" in _ACQUIRE_LUA

    def test_returns_one_on_success(self):
        assert "return 1" in _ACQUIRE_LUA

    def test_sets_key_ttl_to_double_lease(self):
        # Safety net: the ZSET key itself expires at ttl*2
        assert 'redis.call("EXPIRE", key, ttl * 2)' in _ACQUIRE_LUA

    def test_score_is_server_time_plus_ttl(self):
        assert "local score = now + ttl" in _ACQUIRE_LUA


class TestReleaseLuaScript:
    """The release script only removes the caller's own token."""

    def test_uses_zrem(self):
        assert 'redis.call("ZREM", key, token)' in _RELEASE_LUA

    def test_returns_one_when_removed(self):
        assert "if removed > 0 then" in _RELEASE_LUA
        assert "return 1" in _RELEASE_LUA

    def test_returns_zero_when_not_found(self):
        assert "return 0" in _RELEASE_LUA

    def test_does_not_touch_other_tokens(self):
        # No ZREMRANGEBYSCORE or DEL in release — only the exact token
        assert "ZREMRANGEBYSCORE" not in _RELEASE_LUA
        assert "DEL" not in _RELEASE_LUA


class TestRenewLuaScript:
    """The renew script extends the lease only if the token still exists."""

    def test_uses_redis_server_time(self):
        assert 'redis.call("TIME")' in _RENEW_LUA

    def test_checks_token_exists_before_update(self):
        assert _RENEW_LUA.index("ZSCORE") < _RENEW_LUA.index("ZADD")

    def test_returns_zero_when_lease_lost(self):
        assert "if not score then" in _RENEW_LUA
        assert "return 0" in _RENEW_LUA

    def test_updates_score_to_now_plus_ttl(self):
        assert "local new_score = now + ttl" in _RENEW_LUA

    def test_sets_key_ttl_to_double_lease(self):
        assert 'redis.call("EXPIRE", key, ttl * 2)' in _RENEW_LUA

    def test_returns_one_on_success(self):
        assert "return 1" in _RENEW_LUA


class TestCountLuaScript:
    """The count script purges expired entries before counting."""

    def test_uses_redis_server_time(self):
        assert 'redis.call("TIME")' in _COUNT_LUA

    def test_removes_expired_entries(self):
        assert "ZREMRANGEBYSCORE" in _COUNT_LUA

    def test_purges_expired_before_counting(self):
        # Count must see the post-purge cardinality, not the raw ZCARD
        assert _COUNT_LUA.index("ZREMRANGEBYSCORE") < _COUNT_LUA.index("ZCARD")

    def test_returns_zcard(self):
        assert "ZCARD" in _COUNT_LUA

    def test_does_not_add_or_remove_tokens(self):
        assert "ZADD" not in _COUNT_LUA
        assert "ZREM" not in _COUNT_LUA.replace("ZREMRANGEBYSCORE", "")


class TestTokenHelpers:
    """Token formats distinguish local fall-open from Redis-backed leases."""

    def test_local_token_prefix(self):
        assert _local_token().startswith("local_")

    def test_redis_token_prefix(self):
        assert _redis_token().startswith("redis_")

    def test_local_token_is_16_hex_chars(self):
        token = _local_token()
        suffix = token[len("local_"):]
        assert len(suffix) == 16
        int(suffix, 16)  # must be hex

    def test_redis_token_is_16_hex_chars(self):
        token = _redis_token()
        suffix = token[len("redis_"):]
        assert len(suffix) == 16
        int(suffix, 16)  # must be hex

    def test_local_tokens_unique(self):
        assert _local_token() != _local_token()

    def test_redis_tokens_unique(self):
        assert _redis_token() != _redis_token()


class TestErrorType:
    """DistributedConcurrencyError is the public failure contract."""

    def test_is_exception_subclass(self):
        assert issubclass(DistributedConcurrencyError, Exception)

    def test_can_be_raised_and_caught(self):
        with pytest.raises(DistributedConcurrencyError, match="redis down"):
            raise DistributedConcurrencyError("redis down")


class TestConstructorLazyState:
    """The constructor does not connect; all Redis state is lazy."""

    def test_initial_state_is_disconnected(self):
        g = OcrDistributedConcurrency(redis_url="redis://localhost:6379/0")
        assert g._redis is None
        assert g._lua_acquire is None
        assert g._lua_release is None
        assert g._lua_renew is None
        assert g._lua_count is None
        assert g._retry_after_monotonic == 0.0
        assert g._last_init_error == ""

    def test_is_connected_false_initially(self):
        g = OcrDistributedConcurrency(redis_url="redis://localhost:6379/0")
        assert g.is_connected is False

    def test_redis_url_stored(self):
        g = OcrDistributedConcurrency(redis_url="redis://example:6379/1")
        assert g._redis_url == "redis://example:6379/1"

    def test_ensure_redis_returns_existing_client_without_reconnect(self):
        g = OcrDistributedConcurrency(redis_url="redis://localhost:6379/0")
        fake = MagicMock()
        g._redis = fake
        result = g._ensure_redis()
        # Coroutine must be awaited; use asyncio in the test below
        import asyncio

        assert asyncio.run(result) is fake


class TestCloseAndInvalidate:
    """close() and _invalidate_redis() clear all Redis state."""

    @pytest.mark.asyncio
    async def test_close_clears_client_and_all_scripts(self):
        g = OcrDistributedConcurrency(redis_url="redis://localhost:6379/0")
        fake = MagicMock()
        fake.aclose = AsyncMock()
        g._redis = fake
        g._lua_acquire = MagicMock()
        g._lua_release = MagicMock()
        g._lua_renew = MagicMock()
        g._lua_count = MagicMock()
        await g.close()
        assert g._redis is None
        assert g._lua_acquire is None
        assert g._lua_release is None
        assert g._lua_renew is None
        assert g._lua_count is None
        assert g.is_connected is False
        fake.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_invalidate_closes_client_sets_backoff(self):
        g = OcrDistributedConcurrency(redis_url="redis://localhost:6379/0")
        fake = MagicMock()
        fake.aclose = AsyncMock()
        g._redis = fake
        g._lua_acquire = MagicMock()
        g._lua_release = MagicMock()
        g._lua_renew = MagicMock()
        g._lua_count = MagicMock()
        await g._invalidate_redis(RuntimeError("down"))
        assert g._redis is None
        assert g._lua_acquire is None
        assert g._lua_release is None
        assert g._lua_renew is None
        assert g._lua_count is None
        assert g._retry_after_monotonic > 0.0
        assert "Redis unavailable" in g._last_init_error
        assert "down" in g._last_init_error
        fake.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ensure_redis_during_backoff_dev_returns_none(self):
        g = OcrDistributedConcurrency(redis_url="redis://localhost:6379/0")
        g._profile = "development"
        g._retry_after_monotonic = float("inf")
        assert await g._ensure_redis() is None

    @pytest.mark.asyncio
    async def test_ensure_redis_during_backoff_cloud_raises_preserved_message(self):
        g = OcrDistributedConcurrency(redis_url="redis://localhost:6379/0")
        g._profile = "cloud_api"
        g._retry_after_monotonic = float("inf")
        g._last_init_error = "previous failure message"
        with pytest.raises(
            DistributedConcurrencyError, match="previous failure message"
        ):
            await g._ensure_redis()

    @pytest.mark.asyncio
    async def test_close_does_not_reset_backoff_or_error(self):
        # Pinned defect: close() clears the client and scripts but leaves
        # _retry_after_monotonic and _last_init_error unchanged, so a later
        # _ensure_redis() in cloud still fails fast with the stale message.
        g = OcrDistributedConcurrency(redis_url="redis://localhost:6379/0")
        g._retry_after_monotonic = 123.0
        g._last_init_error = "stale error"
        await g.close()
        assert g._retry_after_monotonic == 123.0
        assert g._last_init_error == "stale error"


class TestAcquireDecisionMatrix:
    """acquire_global return/raise semantics by profile and Redis state."""

    @pytest.mark.asyncio
    async def test_dev_no_redis_url_returns_local_token(self):
        g = OcrDistributedConcurrency(redis_url="")
        g._profile = "development"
        token = await g.acquire_global(capacity=1, ttl_sec=30)
        assert token is not None
        assert token.startswith("local_")

    @pytest.mark.asyncio
    async def test_cloud_no_redis_url_raises(self):
        g = OcrDistributedConcurrency(redis_url="")
        g._profile = "cloud_api"
        with pytest.raises(DistributedConcurrencyError, match="REDIS_URL not configured"):
            await g.acquire_global(capacity=1, ttl_sec=30)

    @pytest.mark.asyncio
    async def test_acquire_success_returns_redis_token(self):
        g = OcrDistributedConcurrency(redis_url="redis://localhost:6379/0")
        g._profile = "development"
        g._redis = MagicMock()
        g._lua_acquire = AsyncMock(return_value=1)
        token = await g.acquire_global(capacity=2, ttl_sec=60)
        assert token is not None
        assert token.startswith("redis_")
        g._lua_acquire.assert_awaited_once_with(
            keys=[_OCR_CONCURRENCY_KEY], args=[2, 60, token]
        )

    @pytest.mark.asyncio
    async def test_acquire_at_capacity_returns_none(self):
        g = OcrDistributedConcurrency(redis_url="redis://localhost:6379/0")
        g._profile = "development"
        g._redis = MagicMock()
        g._lua_acquire = AsyncMock(return_value=0)
        assert await g.acquire_global(capacity=1, ttl_sec=30) is None

    @pytest.mark.asyncio
    async def test_dev_acquire_error_falls_open_to_local_token(self):
        g = OcrDistributedConcurrency(redis_url="redis://localhost:6379/0")
        g._profile = "development"
        g._redis = MagicMock()
        g._lua_acquire = AsyncMock(side_effect=RuntimeError("boom"))
        token = await g.acquire_global(capacity=1, ttl_sec=30)
        assert token is not None
        assert token.startswith("local_")
        # Client is invalidated for backoff
        assert g._redis is None

    @pytest.mark.asyncio
    async def test_cloud_acquire_error_raises_and_invalidates(self):
        g = OcrDistributedConcurrency(redis_url="redis://localhost:6379/0")
        g._profile = "cloud_api"
        g._redis = MagicMock()
        g._lua_acquire = AsyncMock(side_effect=RuntimeError("boom"))
        with pytest.raises(DistributedConcurrencyError, match="Redis error acquiring"):
            await g.acquire_global(capacity=1, ttl_sec=30)
        assert g._redis is None
        assert g._retry_after_monotonic > 0.0


class TestReleaseDecisionMatrix:
    """release_global is best-effort after Redis init; local tokens short-circuit.

    Pinned defect: in cloud with no REDIS_URL, a redis_ token still raises
    from _ensure_redis() before reaching the best-effort try/except.
    """

    @pytest.mark.asyncio
    async def test_release_none_is_true(self):
        g = OcrDistributedConcurrency(redis_url="redis://localhost:6379/0")
        assert await g.release_global(None) is True

    @pytest.mark.asyncio
    async def test_release_empty_is_true(self):
        g = OcrDistributedConcurrency(redis_url="redis://localhost:6379/0")
        assert await g.release_global("") is True

    @pytest.mark.asyncio
    async def test_release_local_token_is_true_without_redis(self):
        g = OcrDistributedConcurrency(redis_url="")
        g._profile = "development"
        token = await g.acquire_global(capacity=1, ttl_sec=30)
        assert await g.release_global(token) is True

    @pytest.mark.asyncio
    async def test_release_unknown_redis_token_returns_false(self):
        g = OcrDistributedConcurrency(redis_url="redis://localhost:6379/0")
        g._profile = "development"
        g._redis = MagicMock()
        g._lua_release = AsyncMock(return_value=0)
        assert await g.release_global("redis_unknown") is False

    @pytest.mark.asyncio
    async def test_release_known_redis_token_returns_true(self):
        g = OcrDistributedConcurrency(redis_url="redis://localhost:6379/0")
        g._profile = "development"
        g._redis = MagicMock()
        g._lua_release = AsyncMock(return_value=1)
        assert await g.release_global("redis_known") is True
        g._lua_release.assert_awaited_once_with(
            keys=[_OCR_CONCURRENCY_KEY], args=["redis_known"]
        )

    @pytest.mark.asyncio
    async def test_cloud_release_with_no_redis_url_raises(self):
        # Pinned defect: release_global is best-effort only AFTER Redis is
        # initialized. In cloud with no REDIS_URL, _ensure_redis() raises
        # before the try/except, so release is NOT best-effort on this path.
        g = OcrDistributedConcurrency(redis_url="")
        g._profile = "cloud_api"
        with pytest.raises(
            DistributedConcurrencyError, match="REDIS_URL not configured"
        ):
            await g.release_global("redis_tok")

    @pytest.mark.asyncio
    async def test_release_error_returns_true_best_effort(self):
        # Even in cloud, release is best-effort: it invalidates but returns True
        g = OcrDistributedConcurrency(redis_url="redis://localhost:6379/0")
        g._profile = "cloud_api"
        g._redis = MagicMock()
        g._lua_release = AsyncMock(side_effect=RuntimeError("boom"))
        assert await g.release_global("redis_tok") is True
        assert g._redis is None


class TestRenewDecisionMatrix:
    """renew_global returns False on lost lease; profile-dependent on error."""

    @pytest.mark.asyncio
    async def test_renew_empty_token_returns_false(self):
        g = OcrDistributedConcurrency(redis_url="redis://localhost:6379/0")
        assert await g.renew_global("") is False

    @pytest.mark.asyncio
    async def test_renew_local_token_without_redis_returns_false(self):
        g = OcrDistributedConcurrency(redis_url="")
        g._profile = "development"
        token = await g.acquire_global(capacity=1, ttl_sec=30)
        assert await g.renew_global(token, ttl_sec=30) is False

    @pytest.mark.asyncio
    async def test_renew_success_returns_true(self):
        g = OcrDistributedConcurrency(redis_url="redis://localhost:6379/0")
        g._profile = "development"
        g._redis = MagicMock()
        g._lua_renew = AsyncMock(return_value=1)
        assert await g.renew_global("redis_tok", ttl_sec=30) is True
        g._lua_renew.assert_awaited_once_with(
            keys=[_OCR_CONCURRENCY_KEY], args=["redis_tok", 30]
        )

    @pytest.mark.asyncio
    async def test_renew_lost_lease_returns_false(self):
        g = OcrDistributedConcurrency(redis_url="redis://localhost:6379/0")
        g._profile = "development"
        g._redis = MagicMock()
        g._lua_renew = AsyncMock(return_value=0)
        assert await g.renew_global("redis_tok", ttl_sec=30) is False

    @pytest.mark.asyncio
    async def test_dev_renew_error_returns_true_best_effort(self):
        g = OcrDistributedConcurrency(redis_url="redis://localhost:6379/0")
        g._profile = "development"
        g._redis = MagicMock()
        g._lua_renew = AsyncMock(side_effect=RuntimeError("boom"))
        assert await g.renew_global("redis_tok", ttl_sec=30) is True
        assert g._redis is None

    @pytest.mark.asyncio
    async def test_cloud_renew_error_raises(self):
        g = OcrDistributedConcurrency(redis_url="redis://localhost:6379/0")
        g._profile = "cloud_api"
        g._redis = MagicMock()
        g._lua_renew = AsyncMock(side_effect=RuntimeError("boom"))
        with pytest.raises(DistributedConcurrencyError, match="Redis error renewing"):
            await g.renew_global("redis_tok", ttl_sec=30)
        assert g._redis is None


class TestCountDecisionMatrix:
    """current_count returns None in dev when Redis is unavailable or errors.

    In cloud_api with no REDIS_URL, _ensure_redis() raises before the
    count operation; that fail-closed boundary is pinned separately above.
    """

    @pytest.mark.asyncio
    async def test_cloud_renew_with_no_redis_url_raises(self):
        g = OcrDistributedConcurrency(redis_url="")
        g._profile = "cloud_api"
        with pytest.raises(
            DistributedConcurrencyError, match="REDIS_URL not configured"
        ):
            await g.renew_global("redis_tok", ttl_sec=30)

    @pytest.mark.asyncio
    async def test_cloud_count_with_no_redis_url_raises(self):
        g = OcrDistributedConcurrency(redis_url="")
        g._profile = "cloud_api"
        with pytest.raises(
            DistributedConcurrencyError, match="REDIS_URL not configured"
        ):
            await g.current_count()

    @pytest.mark.asyncio
    async def test_count_without_redis_returns_none(self):
        g = OcrDistributedConcurrency(redis_url="")
        g._profile = "development"
        assert await g.current_count() is None

    @pytest.mark.asyncio
    async def test_count_with_mock_returns_int(self):
        g = OcrDistributedConcurrency(redis_url="redis://localhost:6379/0")
        g._profile = "development"
        g._redis = MagicMock()
        g._lua_count = AsyncMock(return_value=3)
        assert await g.current_count() == 3
        g._lua_count.assert_awaited_once_with(
            keys=[_OCR_CONCURRENCY_KEY], args=[]
        )

    @pytest.mark.asyncio
    async def test_count_error_returns_none_and_invalidates(self):
        g = OcrDistributedConcurrency(redis_url="redis://localhost:6379/0")
        g._profile = "cloud_api"
        g._redis = MagicMock()
        g._lua_count = AsyncMock(side_effect=RuntimeError("boom"))
        assert await g.current_count() is None
        assert g._redis is None
