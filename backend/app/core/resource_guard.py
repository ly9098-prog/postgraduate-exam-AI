"""Resource Guard — unified production resource protection.

Combines system-level monitoring (RSS, memory, event-loop lag) with
per-pipeline budgeting (input size, pages, pixels, OCR calls, artifacts).

Usage::

    from app.core.resource_guard import resource_guard

    # System-level check (before starting any pipeline)
    ok, reason = resource_guard.can_accept_work()
    if not ok:
        return {"error": "resource_pressure", "detail": reason}

    # Async context manager (preferred — atomic acquire/release)
    async with resource_guard.acquire_pipeline() as acquired:
        if not acquired:
            return JSONResponse({"error": "resource_pressure"}, status_code=503)
        # ... pipeline work ...

    # Pipeline-level check (per-pipeline limits)
    guard = ResourceGuard.for_profile(profile)
    guard.check_input_bytes(file_size)
    guard.check_page_count(page_count)
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass

from app.core.config import settings
from app.core.deployment_profile import DeploymentProfile, detect_deployment_profile

logger = logging.getLogger("postgraduate-ai.resource_guard")


# ── Error Codes ──

RESOURCE_PRESSURE = "RESOURCE_PRESSURE"
INPUT_TOO_LARGE = "INPUT_TOO_LARGE"
PAGE_LIMIT_EXCEEDED = "PAGE_LIMIT_EXCEEDED"
PIXEL_BUDGET_EXCEEDED = "PIXEL_BUDGET_EXCEEDED"
CONCURRENCY_LIMIT_EXCEEDED = "CONCURRENCY_LIMIT_EXCEEDED"
REMOTE_OCR_CALL_BUDGET_EXCEEDED = "REMOTE_OCR_CALL_BUDGET_EXCEEDED"
ARTIFACT_SIZE_LIMIT_EXCEEDED = "ARTIFACT_SIZE_LIMIT_EXCEEDED"
PIPELINE_TIMEOUT = "PIPELINE_TIMEOUT"
PAGE_TIMEOUT = "PAGE_TIMEOUT"

# ── Redis-backed distributed semaphore for cross-process pipeline admission ──

_RESOURCE_PREFIX = "resource:active_pipelines"
_RESOURCE_SEM_KEY = f"{_RESOURCE_PREFIX}:semaphore"
_RESOURCE_TTL = 3600  # 1 hour max pipeline lifetime (safety net for crashes)

# Lua: atomic check-and-increment (rejects when at capacity)
# KEYS: [semaphore_key]
# ARGS: [max_concurrent, ttl_sec]
# Returns: new_count on success (>0), -1 if at capacity
_LUA_ACQUIRE_SEM = """
local key = KEYS[1]
local max = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])
local current = redis.call("GET", key)
if current then
    current = tonumber(current)
else
    current = 0
end
if current >= max then
    return -1
end
redis.call("INCR", key)
redis.call("EXPIRE", key, ttl)
return current + 1
"""

# Lua: atomic decrement (never below 0)
_LUA_RELEASE_SEM = """
local key = KEYS[1]
local current = redis.call("GET", key)
if current then
    current = tonumber(current)
    if current > 0 then
        redis.call("DECR", key)
        return current - 1
    end
end
return 0
"""

_LUA_GET_COUNT = """
local key = KEYS[1]
local current = redis.call("GET", key)
if current then
    return tonumber(current)
end
return 0
"""


class ResourceGuardError(ValueError):
    """Raised when a resource guard limit is exceeded."""
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


# ── System-level thresholds ──


@dataclass
class SystemThresholds:
    """System resource thresholds that trigger protective actions."""
    max_rss_mb: float = 1024
    min_available_memory_mb: float = 256
    max_event_loop_lag_ms: float = 500
    max_active_pipelines: int = 1
    max_temp_disk_mb: float = 512


@dataclass
class SystemMetrics:
    """Snapshot of current system resource usage."""
    rss_mb: float = 0.0
    available_memory_mb: float = 0.0
    event_loop_lag_ms: float = 0.0
    active_pipelines: int = 0
    temp_disk_usage_mb: float = 0.0


# ── Unified ResourceGuard ──


class ResourceGuard:
    """Combined system-level + per-pipeline resource guard.

    Provides:
    - ``can_accept_work()`` — system-level check before accepting new jobs
    - ``check_*()`` — per-pipeline budget checks
    - ``for_profile()`` — factory with profile-appropriate defaults

    Active pipeline counting uses a Redis-backed semaphore for cross-process
    coordination. Falls back to process-local counting when Redis is
    unavailable (dev only).
    """

    # ── Class-level fallback for when Redis is unavailable ──
    _active_pipeline_count: int = 0

    # ── Construction ──

    def __init__(
        self,
        thresholds: SystemThresholds | None = None,
        metrics_provider: Callable[[], SystemMetrics] | None = None,
    ):
        # System-level
        self._thresholds = thresholds or SystemThresholds()
        self._metrics_provider = metrics_provider or self._collect_system_metrics

        # Per-pipeline limits (default: production cloud_api)
        self.max_input_bytes: int = 10 * 1024 * 1024
        self.max_pages: int = 50
        self.max_pixel_budget: int = 4000 * 4000 * 50
        self.max_concurrent_documents: int = 1
        self.max_concurrent_pages: int = 1
        self.max_remote_ocr_calls: int = 100
        self.max_artifact_bytes: int = 50 * 1024 * 1024
        self.max_pipeline_seconds: int = 1800
        self.max_page_seconds: int = 120

        # Per-pipeline mutable state
        self._render_pixels_consumed: int = 0
        self._remote_ocr_calls: int = 0
        self._artifact_bytes_written: int = 0

    # ── Redis semaphore for distributed pipeline counting ──
    # Uses sync Redis client since increment/decrement are called from
    # sync contexts (finally blocks, __del__, etc.).

    @staticmethod
    def _get_redis_client():
        """Create a sync Redis client for semaphore operations."""
        if not settings.REDIS_URL:
            return None
        try:
            import redis as redis_sync
            return redis_sync.from_url(
                settings.REDIS_URL,
                socket_connect_timeout=2,
                socket_timeout=2,
                decode_responses=True,
            )
        except Exception:
            return None

    def _redis_active_count_sync(self) -> int:
        """Return current active pipeline count from Redis (sync)."""
        client = self._get_redis_client()
        if client is None:
            return ResourceGuard._active_pipeline_count
        try:
            val = client.get(_RESOURCE_SEM_KEY)
            return int(val) if val else 0
        except Exception:
            return ResourceGuard._active_pipeline_count
        finally:
            try:
                client.close()
            except Exception:
                pass

    def _redis_acquire_sync(self, max_concurrent: int) -> bool:
        """Try to acquire Redis semaphore (sync). True if under capacity.

        In production/cloud_api, Redis failure fails closed (returns False).
        In dev/local, falls back to process-local counting.
        """
        client = self._get_redis_client()
        if client is None:
            if self._is_restricted():
                return False
            current = ResourceGuard._active_pipeline_count
            if current >= max_concurrent:
                return False
            ResourceGuard._active_pipeline_count += 1
            return True
        try:
            sha = client.script_load(_LUA_ACQUIRE_SEM)
            result = client.evalsha(sha, 1, _RESOURCE_SEM_KEY,
                                    str(max_concurrent), str(_RESOURCE_TTL))
            count = int(result) if result else 0
            return count > 0
        except Exception:
            if self._is_restricted():
                return False
            current = ResourceGuard._active_pipeline_count
            if current >= max_concurrent:
                return False
            ResourceGuard._active_pipeline_count += 1
            return True
        finally:
            try:
                client.close()
            except Exception:
                pass

    def _redis_release_sync(self) -> None:
        """Release Redis semaphore (sync)."""
        client = self._get_redis_client()
        if client is None:
            ResourceGuard._active_pipeline_count = max(
                0, ResourceGuard._active_pipeline_count - 1
            )
            return
        try:
            sha = client.script_load(_LUA_RELEASE_SEM)
            client.evalsha(sha, 1, _RESOURCE_SEM_KEY)
        except Exception:
            ResourceGuard._active_pipeline_count = max(
                0, ResourceGuard._active_pipeline_count - 1
            )
        finally:
            try:
                client.close()
            except Exception:
                pass

    # ── Async Redis semaphore (preferred path for async callers) ──

    @staticmethod
    async def _get_async_redis_client():
        """Create an async Redis client for semaphore operations."""
        if not settings.REDIS_URL:
            return None
        try:
            import redis.asyncio as redis_async
            return redis_async.from_url(
                settings.REDIS_URL,
                socket_connect_timeout=2,
                socket_timeout=2,
                decode_responses=True,
            )
        except Exception:
            return None

    def _is_restricted(self) -> bool:
        """Check if we're in a restricted environment (fail-closed on Redis failure)."""
        if settings.APP_ENV == "production":
            return True
        try:
            return detect_deployment_profile() == DeploymentProfile.CLOUD_API
        except Exception:
            return True  # fail closed

    async def _redis_acquire_async(self, max_concurrent: int) -> bool:
        """Try to acquire Redis semaphore (async). True if under capacity.

        In production/cloud_api, Redis failure fails closed (returns False).
        In dev/local, falls back to process-local counting.
        """
        client = await self._get_async_redis_client()
        if client is None:
            if self._is_restricted():
                return False
            current = ResourceGuard._active_pipeline_count
            if current >= max_concurrent:
                return False
            ResourceGuard._active_pipeline_count += 1
            return True
        try:
            sha = await client.script_load(_LUA_ACQUIRE_SEM)
            result = await client.evalsha(sha, 1, _RESOURCE_SEM_KEY,
                                          str(max_concurrent), str(_RESOURCE_TTL))
            count = int(result) if result else 0
            return count > 0
        except Exception:
            if self._is_restricted():
                return False
            current = ResourceGuard._active_pipeline_count
            if current >= max_concurrent:
                return False
            ResourceGuard._active_pipeline_count += 1
            return True
        finally:
            try:
                await client.aclose()
            except Exception:
                pass

    async def _redis_release_async(self) -> None:
        """Release Redis semaphore (async). Safe to call even on failed acquire."""
        client = await self._get_async_redis_client()
        if client is None:
            ResourceGuard._active_pipeline_count = max(
                0, ResourceGuard._active_pipeline_count - 1
            )
            return
        try:
            sha = await client.script_load(_LUA_RELEASE_SEM)
            await client.evalsha(sha, 1, _RESOURCE_SEM_KEY)
        except Exception:
            ResourceGuard._active_pipeline_count = max(
                0, ResourceGuard._active_pipeline_count - 1
            )
        finally:
            try:
                await client.aclose()
            except Exception:
                pass

    # ── Async context manager (preferred API) ──

    @asynccontextmanager
    async def acquire_pipeline(self, *, timeout: float = 5.0):
        """Async context manager for pipeline admission.

        Atomically acquires a pipeline slot. Yields True on success,
        False if at capacity or Redis unavailable (production).

        Automatically releases on exit, exception, or cancellation.

        Usage::

            async with resource_guard.acquire_pipeline() as acquired:
                if not acquired:
                    return JSONResponse(
                        {"error": "RESOURCE_PRESSURE"},
                        status_code=503,
                        headers={"Retry-After": "30"},
                    )
                # ... pipeline work ...
        """
        acquired = False
        try:
            acquired = await asyncio.wait_for(
                self._redis_acquire_async(self._thresholds.max_active_pipelines),
                timeout=timeout,
            )
            yield acquired
        except TimeoutError:
            yield False
        finally:
            if acquired:
                await self._redis_release_async()

    @classmethod
    def for_profile(cls, profile: DeploymentProfile) -> ResourceGuard:
        """Create a ResourceGuard with defaults for the deployment profile."""
        guard = cls()
        if profile == DeploymentProfile.CLOUD_API:
            guard.max_input_bytes = 5 * 1024 * 1024   # 5MB (per task doc)
            guard.max_pages = 30                       # 30 pages (per task doc)
            guard.max_pixel_budget = 4000 * 4000 * 30
            guard.max_remote_ocr_calls = 60            # ~2 calls/page for 30 pages
            guard.max_artifact_bytes = 50 * 1024 * 1024
            guard.max_pipeline_seconds = 1800
            guard.max_page_seconds = 120
            guard.max_concurrent_documents = 1
            guard.max_concurrent_pages = 1
            guard._thresholds = SystemThresholds(
                max_active_pipelines=1,
            )
        else:
            guard.max_input_bytes = 200 * 1024 * 1024
            guard.max_pages = 600
            guard.max_pixel_budget = 4000 * 4000 * 600
            guard.max_concurrent_pages = 3
            guard.max_remote_ocr_calls = 500
            guard.max_artifact_bytes = 500 * 1024 * 1024
            guard.max_pipeline_seconds = 7200
            guard.max_page_seconds = 600
            guard._thresholds = SystemThresholds(
                max_active_pipelines=3,
                max_rss_mb=3072,
            )
        return guard

    # ── System-level check ──

    def can_accept_work(self) -> tuple[bool, str | None]:
        """Check if the server can accept new pipeline work.

        Returns (True, None) if OK, or (False, reason) if resource pressure.
        Uses Redis-backed semaphore for active pipeline counting.
        """
        metrics = self._metrics_provider()

        if metrics.rss_mb > self._thresholds.max_rss_mb:
            return False, f"RSS {metrics.rss_mb:.0f}MB exceeds limit {self._thresholds.max_rss_mb}MB"

        if metrics.available_memory_mb > 0 and metrics.available_memory_mb < self._thresholds.min_available_memory_mb:
            return False, f"Available memory {metrics.available_memory_mb:.0f}MB below minimum {self._thresholds.min_available_memory_mb}MB"

        if metrics.event_loop_lag_ms > self._thresholds.max_event_loop_lag_ms:
            return False, f"Event loop lag {metrics.event_loop_lag_ms:.0f}ms exceeds limit {self._thresholds.max_event_loop_lag_ms}ms"

        # Check Redis-based active pipeline count
        active = self._redis_active_count_sync()
        if active >= self._thresholds.max_active_pipelines:
            return False, f"Active pipelines {active} at limit {self._thresholds.max_active_pipelines}"

        if metrics.temp_disk_usage_mb > self._thresholds.max_temp_disk_mb:
            return False, f"Temp disk {metrics.temp_disk_usage_mb:.0f}MB exceeds limit {self._thresholds.max_temp_disk_mb}MB"

        return True, None

    @staticmethod
    def _collect_system_metrics() -> SystemMetrics:
        """Collect real resource metrics from the system."""
        m = SystemMetrics()

        try:
            with open("/proc/self/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        m.rss_mb = int(line.split()[1]) / 1024
                        break
        except OSError:
            pass

        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemAvailable:"):
                        m.available_memory_mb = int(line.split()[1]) / 1024
                        break
        except OSError:
            pass

        m.active_pipelines = ResourceGuard._active_pipeline_count

        return m

    def get_system_metrics(self) -> SystemMetrics:
        m = self._metrics_provider()
        # Override with Redis count for accuracy
        m.active_pipelines = self._redis_active_count_sync()
        return m

    # ── Pipeline count tracking (Redis-backed, cross-process) ──

    def increment_pipeline_count(self) -> bool:
        """Increment active pipeline count using Redis semaphore.

        Uses Redis Lua for atomic cross-process counting.
        In production/cloud_api, Redis failure fails closed (returns False).
        In dev/local, falls back to process-local counting.

        Returns True if the count was successfully incremented (under capacity).
        """
        return self._redis_acquire_sync(self._thresholds.max_active_pipelines)

    def decrement_pipeline_count(self) -> None:
        """Decrement active pipeline count using Redis semaphore.

        Safe to call even if increment was process-local (Redis fallback).
        """
        self._redis_release_sync()

    # ── Per-pipeline budget checks ──

    def check_input_bytes(self, size: int) -> None:
        if size > self.max_input_bytes:
            raise ResourceGuardError(
                INPUT_TOO_LARGE,
                f"Input {size} bytes exceeds limit {self.max_input_bytes}",
            )

    def check_page_count(self, count: int) -> None:
        if count > self.max_pages:
            raise ResourceGuardError(
                PAGE_LIMIT_EXCEEDED,
                f"Page count {count} exceeds limit {self.max_pages}",
            )

    def check_render_pixels(self, pixels: int) -> None:
        new_total = self._render_pixels_consumed + pixels
        if new_total > self.max_pixel_budget:
            raise ResourceGuardError(
                PIXEL_BUDGET_EXCEEDED,
                f"Render pixel budget {new_total} exceeds limit {self.max_pixel_budget}",
            )
        self._render_pixels_consumed = new_total

    def check_remote_ocr_call(self) -> None:
        if self._remote_ocr_calls >= self.max_remote_ocr_calls:
            raise ResourceGuardError(
                REMOTE_OCR_CALL_BUDGET_EXCEEDED,
                f"Remote OCR calls {self._remote_ocr_calls} exceeds limit {self.max_remote_ocr_calls}",
            )
        self._remote_ocr_calls += 1

    def check_artifact_bytes(self, size: int) -> None:
        new_total = self._artifact_bytes_written + size
        if new_total > self.max_artifact_bytes:
            raise ResourceGuardError(
                ARTIFACT_SIZE_LIMIT_EXCEEDED,
                f"Artifact size {new_total} exceeds limit {self.max_artifact_bytes}",
            )
        self._artifact_bytes_written = new_total


# ── Module-level singleton ──

resource_guard = ResourceGuard()
