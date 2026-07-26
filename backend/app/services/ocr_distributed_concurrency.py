"""Distributed OCR concurrency via Redis ZSET.

Limits the number of concurrent OCR requests across all worker processes
using a Redis-backed ZSET reservation system.

Keys:
    ``ocr:v2:concurrency`` — ZSET member = reservation token, score = expiry timestamp.

Usage::

    guard = OcrDistributedConcurrency(redis_url="redis://...")
    token = await guard.acquire_global(capacity=2, ttl_sec=60)
    if token:
        try:
            # Do OCR work
            ...
        finally:
            await guard.release_global(token)

Design:
- ``ZREMRANGEBYSCORE`` expired entries before each acquire.
- ``ZCARD`` < capacity → ``ZADD`` with expiry score.
- ``ZREM`` on release — only removes our own token.
- Production/cloud: Redis error → fail-closed (raises ``DistributedConcurrencyError``).
- Local semaphore (``asyncio.Semaphore``) kept as local complement.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from app.core.config import settings
from app.core.deployment_profile import DeploymentProfile, detect_deployment_profile

logger = logging.getLogger(__name__)

_OCR_CONCURRENCY_KEY = "ocr:v2:concurrency"
_ACQUIRE_LUA = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])
local token = ARGV[3]

-- Use Redis server time for clock-skew-safe expiry
local redis_now = redis.call("TIME")
local now = tonumber(redis_now[1])

-- Remove expired entries
redis.call("ZREMRANGEBYSCORE", key, "-inf", now)

-- Check capacity
local count = redis.call("ZCARD", key)
if count >= capacity then
    return 0  -- at capacity
end

-- Add new entry with server-time based score
local score = now + ttl
redis.call("ZADD", key, score, token)

-- Set TTL on the key itself (safety net)
redis.call("EXPIRE", key, ttl * 2)
return 1  -- acquired
"""

_RELEASE_LUA = """
local key = KEYS[1]
local token = ARGV[1]

-- Only remove if the member exists (our own token)
local removed = redis.call("ZREM", key, token)
if removed > 0 then
    return 1  -- released
end
return 0  -- token not found (not ours or already expired)
"""

_RENEW_LUA = """
local key = KEYS[1]
local token = ARGV[1]
local ttl = tonumber(ARGV[2])

-- Use Redis server time for clock-skew-safe expiry
local redis_now = redis.call("TIME")
local now = tonumber(redis_now[1])

-- Check token exists
local score = redis.call("ZSCORE", key, token)
if not score then
    return 0  -- token not found (lease lost)
end

-- Update score to now + ttl (extend lease)
local new_score = now + ttl
redis.call("ZADD", key, new_score, token)
redis.call("EXPIRE", key, ttl * 2)
return 1  -- renewed
"""


class DistributedConcurrencyError(Exception):
    """Raised when Redis operations fail for distributed concurrency."""


class OcrDistributedConcurrency:
    """Redis-backed distributed OCR concurrency guard.

    Thread/process-safe: all operations are atomic Lua scripts.
    Fail-closed in production: Redis errors raise ``DistributedConcurrencyError``.
    """

    def __init__(
        self,
        redis_url: str | None = None,
    ) -> None:
        self._redis_url = redis_url or settings.REDIS_URL
        self._redis: Any = None  # redis.asyncio.Redis — lazy init
        self._profile = detect_deployment_profile()
        self._lua_acquire: Any = None
        self._lua_release: Any = None
        self._lua_renew: Any = None

    async def _ensure_redis(self) -> Any:
        """Lazy-init the Redis client and register Lua scripts."""
        if self._redis is not None:
            return self._redis

        import redis.asyncio as redis_async

        if not self._redis_url:
            if self._profile == DeploymentProfile.CLOUD_API:
                raise DistributedConcurrencyError(
                    "REDIS_URL not configured — distributed OCR concurrency unavailable "
                    "in cloud profile"
                )
            logger.warning(
                "REDIS_URL not configured — distributed OCR concurrency disabled"
            )
            self._redis = None
            return None

        try:
            self._redis = await redis_async.from_url(
                self._redis_url, decode_responses=True, socket_connect_timeout=5,
            )
            self._lua_acquire = self._redis.register_script(_ACQUIRE_LUA)
            self._lua_release = self._redis.register_script(_RELEASE_LUA)
            self._lua_renew = self._redis.register_script(_RENEW_LUA)
            return self._redis
        except Exception as exc:
            self._redis = None
            if self._profile == DeploymentProfile.CLOUD_API:
                raise DistributedConcurrencyError(
                    f"Failed to connect to Redis for distributed OCR concurrency: {exc}"
                ) from exc
            logger.warning(
                "Failed to connect to Redis for distributed OCR concurrency: %s", exc
            )
            return None

    async def acquire_global(
        self,
        capacity: int | None = None,
        ttl_sec: int | None = None,
    ) -> str | None:
        """Acquire a distributed OCR concurrency slot.

        Args:
            capacity: Maximum concurrent OCR requests (default from settings).
            ttl_sec: Lease duration in seconds (default from settings).

        Returns:
            Reservation token (opaque string), or None if at capacity / Redis unavailable.

        Raises:
            DistributedConcurrencyError: In cloud/production when Redis is unavailable.
        """
        if capacity is None:
            capacity = settings.OCR_GLOBAL_CONCURRENCY
        if ttl_sec is None:
            ttl_sec = settings.OCR_DISTRIBUTED_LEASE_SEC

        redis = await self._ensure_redis()
        if redis is None:
            # Redis unavailable — allow in non-production, fail-closed in production
            if self._profile == DeploymentProfile.CLOUD_API:
                raise DistributedConcurrencyError(
                    "Redis unavailable — distributed OCR concurrency cannot proceed "
                    "in cloud profile"
                )
            # Non-production: fall open (local semaphore still applies)
            return _local_token()

        token = _local_token()
        try:
            result = await self._lua_acquire(
                keys=[_OCR_CONCURRENCY_KEY],
                args=[capacity, ttl_sec, token],
            )
            if result == 1:
                return token
            # At capacity — return None, caller must NOT proceed with OCR
            logger.warning(
                "OCR distributed concurrency at capacity (%d), request rejected", capacity,
            )
            return None
        except Exception as exc:
            if self._profile == DeploymentProfile.CLOUD_API:
                raise DistributedConcurrencyError(
                    f"Redis error acquiring OCR concurrency slot: {exc}"
                ) from exc
            logger.warning("Redis error acquiring OCR concurrency slot: %s", exc)
            return _local_token()  # fall open in non-production

    async def release_global(self, token: str | None) -> bool:
        """Release a previously acquired distributed slot.

        Args:
            token: The reservation token returned by ``acquire_global``.

        Returns:
            True if the token was found and released, False otherwise.
        """
        if not token:
            return True

        redis = await self._ensure_redis()
        if redis is None:
            return True

        try:
            result = await self._lua_release(
                keys=[_OCR_CONCURRENCY_KEY],
                args=[token],
            )
            return result == 1
        except Exception as exc:
            logger.warning("Redis error releasing OCR concurrency slot: %s", exc)
            return True  # best-effort

    async def renew_global(self, token: str, ttl_sec: int | None = None) -> bool:
        """Renew a distributed OCR concurrency slot lease.

        Uses Redis server time for clock-skew-safe expiry calculation.
        This should be called periodically during long OCR operations
        to prevent the slot from being reclaimed by another worker.

        Args:
            token: The reservation token from ``acquire_global``.
            ttl_sec: New lease duration (default from settings).

        Returns:
            True if renewed, False if token not found (lease lost).
        """
        if not token:
            return False
        if ttl_sec is None:
            ttl_sec = settings.OCR_DISTRIBUTED_LEASE_SEC

        redis = await self._ensure_redis()
        if redis is None:
            return False

        try:
            result = await self._lua_renew(
                keys=[_OCR_CONCURRENCY_KEY],
                args=[token, ttl_sec],
            )
            renewed = result == 1
            if not renewed:
                logger.warning("OCR concurrency lease lost: token=%s", token[:8])
            return renewed
        except Exception as exc:
            logger.warning("Redis error renewing OCR concurrency slot: %s", exc)
            if self._profile == DeploymentProfile.CLOUD_API:
                raise DistributedConcurrencyError(
                    f"Redis error renewing OCR concurrency slot: {exc}"
                ) from exc
            return True  # best-effort in non-production

    async def close(self) -> None:
        """Close the Redis connection."""
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception:
                pass
            self._redis = None

    @property
    def is_connected(self) -> bool:
        """Check if Redis is connected."""
        return self._redis is not None

    async def current_count(self) -> int | None:
        """Return the current number of active distributed slots, or None on error."""
        redis = await self._ensure_redis()
        if redis is None:
            return None
        try:
            # Clean expired first
            await redis.zremrangebyscore(_OCR_CONCURRENCY_KEY, "-inf", time.time())
            return await redis.zcard(_OCR_CONCURRENCY_KEY)
        except Exception:
            return None


def _local_token() -> str:
    """Generate a local-only reservation token."""
    return f"local_{uuid.uuid4().hex[:16]}"


# Module-level singleton
_global_concurrency: OcrDistributedConcurrency | None = None


def get_global_concurrency() -> OcrDistributedConcurrency:
    """Return the process-wide OcrDistributedConcurrency singleton."""
    global _global_concurrency
    if _global_concurrency is None:
        _global_concurrency = OcrDistributedConcurrency()
    return _global_concurrency


def reset_global_concurrency() -> None:
    """Reset the singleton (for testing)."""
    global _global_concurrency
    _global_concurrency = None
