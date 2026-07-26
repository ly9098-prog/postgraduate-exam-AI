"""Resource Guard — unified production resource protection.

Combines system-level monitoring (RSS, memory, event-loop lag) with
per-pipeline budgeting (input size, pages, pixels, OCR calls, artifacts).
Redis-backed ZSET reservation replaces the previous INCR/DECR semaphore.

Usage::

    from app.core.resource_guard import resource_guard

    # System-level check (before starting any pipeline)
    ok, reason = resource_guard.can_accept_work()
    if not ok:
        return {"error": "resource_pressure", "detail": reason}

    # Async context manager (preferred — atomic acquire/release)
    async with resource_guard.acquire_pipeline(
        resource_type="import_pipeline",
        task_id=pipeline_id,
        owner_token=worker_id,
    ) as token:
        if not token:
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
import time
import uuid
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

# ── Redis v2 ZSET reservation keys ──
# Uses `{resource_type}` hash tag for cross-key atomicity in cluster mode.

_V2_RESOURCE_ZSET_TPL = "resource:v2:{rt}:zset"
_V2_RESOURCE_META_TPL = "resource:v2:{rt}:meta:{token}"
_V2_RESOURCE_META_PREFIX_TPL = "resource:v2:{rt}:meta:"

# Lua: atomic acquire — clean expired, check capacity, add + metadata
# KEYS: [zset_key, meta_key]
# ARGS: [resource_type, task_id, owner_token, generation, ttl_sec, capacity, token, now_ts]
# Returns: "OK" on success, "" on capacity
_LUA_ACQUIRE_RESERVATION_V2 = """
local zset_key = KEYS[1]
local meta_key = KEYS[2]
local capacity = tonumber(ARGV[6])
local token = ARGV[7]
local now = tonumber(ARGV[8])
local ttl = tonumber(ARGV[5])

-- Clean expired
redis.call("ZREMRANGEBYSCORE", zset_key, "-inf", now)

-- Check capacity
local current = redis.call("ZCARD", zset_key)
if current >= capacity then
    return ""
end

-- Add reservation
local expires_at = now + ttl
redis.call("ZADD", zset_key, expires_at, token)
redis.call("HSET", meta_key,
    "task_id", ARGV[2],
    "owner_token", ARGV[3],
    "generation", ARGV[4],
    "resource_type", ARGV[1],
    "acquired_at", now,
    "expires_at", expires_at,
)
redis.call("EXPIRE", meta_key, ttl + 60)
return "OK"
"""

# Lua: atomic release — verify owner + generation match
# KEYS: [zset_key, meta_key]
# ARGS: [token, owner_token, generation, now_ts]
# Returns: "OK", "OWNER_MISMATCH", "GENERATION_MISMATCH", "NOT_FOUND"
_LUA_RELEASE_RESERVATION_V2 = """
local zset_key = KEYS[1]
local meta_key = KEYS[2]
local token = ARGV[1]
local owner_token = ARGV[2]
local generation = ARGV[3]

-- Check if reservation exists
local exists = redis.call("ZSCORE", zset_key, token)
if not exists then
    return "NOT_FOUND"
end

-- Verify owner
local stored_owner = redis.call("HGET", meta_key, "owner_token")
if stored_owner and stored_owner ~= owner_token then
    return "OWNER_MISMATCH"
end

-- Verify generation (if stored)
local stored_gen = redis.call("HGET", meta_key, "generation")
if stored_gen and generation ~= "0" and stored_gen ~= generation then
    return "GENERATION_MISMATCH"
end

redis.call("ZREM", zset_key, token)
redis.call("DEL", meta_key)
return "OK"
"""

# Lua: atomic renew — verify owner
# KEYS: [zset_key, meta_key]
# ARGS: [token, owner_token, ttl_sec, now_ts]
# Returns: "OK", "OWNER_MISMATCH", "NOT_FOUND"
_LUA_RENEW_RESERVATION_V2 = """
local zset_key = KEYS[1]
local meta_key = KEYS[2]
local token = ARGV[1]
local owner_token = ARGV[2]
local ttl = tonumber(ARGV[3])
local now = tonumber(ARGV[4])

-- Check if reservation exists
local exists = redis.call("ZSCORE", zset_key, token)
if not exists then
    return "NOT_FOUND"
end

-- Verify owner
local stored_owner = redis.call("HGET", meta_key, "owner_token")
if stored_owner and stored_owner ~= owner_token then
    return "OWNER_MISMATCH"
end

local expires_at = now + ttl
redis.call("ZADD", zset_key, expires_at, token)
redis.call("HSET", meta_key, "expires_at", expires_at)
redis.call("EXPIRE", meta_key, ttl + 60)
return "OK"
"""

# Lua: reaper — remove all expired reservations + their metadata
# KEYS: [zset_key, meta_prefix]
# ARGS: [now_ts]
# Returns: count of removed reservations
_LUA_REAPER_RESERVATIONS_V2 = """
local zset_key = KEYS[1]
local meta_prefix = KEYS[2]
local now = tonumber(ARGV[1])

local expired = redis.call("ZRANGEBYSCORE", zset_key, "-inf", now)
local count = 0
for _, member in ipairs(expired) do
    redis.call("ZREM", zset_key, member)
    redis.call("DEL", meta_prefix .. member)
    count = count + 1
end
return count
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


@dataclass
class ReservationInfo:
    """Metadata for an acquired reservation."""
    token: str
    task_id: str
    owner_token: str
    generation: int
    resource_type: str
    acquired_at: float
    expires_at: float


# ── Unified ResourceGuard ──


class ResourceGuard:
    """Combined system-level + per-pipeline resource guard.

    Provides:
    - ``can_accept_work()`` — system-level check before accepting new jobs
    - ``acquire_reservation()`` / ``release_reservation()`` — ZSET-based
    - ``check_*()`` — per-pipeline budget checks
    - ``for_profile()`` — factory with profile-appropriate defaults

    Active pipeline reservation uses a Redis ZSET for cross-process
    coordination with TTL-based crash safety.
    """

    # ── Process-local owner token ──
    _process_owner_token: str = ""

    # ── In-memory reservation registry (for same-process release) ──
    _reservations_by_task: dict[str, ReservationInfo] = {}

    # ── Construction ──

    def __init__(
        self,
        thresholds: SystemThresholds | None = None,
        metrics_provider: Callable[[], SystemMetrics] | None = None,
    ):
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

        # Lua script SHAs (loaded lazily)
        self._lua_acquire_sha: str | None = None
        self._lua_release_sha: str | None = None
        self._lua_renew_sha: str | None = None
        self._lua_reaper_sha: str | None = None

        # Orphan reconciler task
        self._orphan_reconciler_task: asyncio.Task | None = None

    @property
    def process_owner_token(self) -> str:
        if not ResourceGuard._process_owner_token:
            ResourceGuard._process_owner_token = f"proc_{uuid.uuid4().hex[:12]}"
        return ResourceGuard._process_owner_token

    # ── Key builders with hash tags ──

    @staticmethod
    def _zset_key(resource_type: str) -> str:
        return _V2_RESOURCE_ZSET_TPL.format(rt=resource_type)

    @staticmethod
    def _meta_key(resource_type: str, token: str) -> str:
        return _V2_RESOURCE_META_TPL.format(rt=resource_type, token=token)

    @staticmethod
    def _meta_prefix(resource_type: str) -> str:
        return _V2_RESOURCE_META_PREFIX_TPL.format(rt=resource_type)

    # ── Async Redis client ──

    @staticmethod
    async def _get_async_redis():
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
        if settings.APP_ENV == "production":
            return True
        try:
            return detect_deployment_profile() == DeploymentProfile.CLOUD_API
        except Exception:
            return True

    # ── ZSET Reservation API ──

    async def acquire_reservation(
        self,
        resource_type: str,
        task_id: str,
        owner_token: str = "",
        generation: int = 0,
        ttl_sec: int | None = None,
    ) -> str | None:
        """Acquire a reservation slot.

        Args:
            resource_type: e.g. "import_pipeline", "image_pipeline"
            task_id: the task/pipeline identifier
            owner_token: process/worker identifier; defaults to process token
            generation: fencing generation (0 for new tasks)
            ttl_sec: reservation TTL; defaults to PIPELINE_RESERVATION_LEASE_SEC

        Returns reservation token string, or None if at capacity.
        """
        owner_token = owner_token or self.process_owner_token
        ttl_sec = ttl_sec or settings.PIPELINE_RESERVATION_LEASE_SEC
        capacity = self._thresholds.max_active_pipelines

        client = await self._get_async_redis()
        if client is None:
            if self._is_restricted():
                logger.warning("Reservation denied: Redis unavailable in restricted env")
                return None
            logger.warning("Reservation using in-memory fallback")
            return self._acquire_local(capacity, ttl_sec, resource_type, task_id, owner_token, generation)

        try:
            token = uuid.uuid4().hex
            zset_key = self._zset_key(resource_type)
            meta_key = self._meta_key(resource_type, token)

            if self._lua_acquire_sha is None:
                self._lua_acquire_sha = await client.script_load(_LUA_ACQUIRE_RESERVATION_V2)

            result = await client.evalsha(
                self._lua_acquire_sha,
                2,
                zset_key,
                meta_key,
                resource_type,
                task_id,
                owner_token,
                str(generation),
                str(ttl_sec),
                str(capacity),
                token,
                str(int(time.time())),
            )

            if result == "OK":
                return token
            return None
        except Exception as exc:
            logger.warning("Redis reservation acquire error: %s", exc)
            if self._is_restricted():
                return None
            return self._acquire_local(capacity, ttl_sec, resource_type, task_id, owner_token, generation)
        finally:
            if client:
                await client.aclose()

    def _acquire_local(
        self,
        capacity: int,
        ttl_sec: int,
        resource_type: str,
        task_id: str,
        owner_token: str,
        generation: int,
    ) -> str | None:
        """In-process fallback acquire (dev only)."""
        active = sum(
            1 for r in ResourceGuard._reservations_by_task.values()
            if r.resource_type == resource_type and r.expires_at > time.time()
        )
        if active >= capacity:
            return None
        token = uuid.uuid4().hex
        now = time.time()
        info = ReservationInfo(
            token=token,
            task_id=task_id,
            owner_token=owner_token,
            generation=generation,
            resource_type=resource_type,
            acquired_at=now,
            expires_at=now + ttl_sec,
        )
        ResourceGuard._reservations_by_task[token] = info
        return token

    async def release_reservation(
        self,
        token: str,
        resource_type: str = "import_pipeline",
        owner_token: str = "",
        generation: int = 0,
    ) -> bool:
        """Release a reservation. Returns True if released, False if not found."""
        owner_token = owner_token or self.process_owner_token

        # Try local first
        local_info = ResourceGuard._reservations_by_task.get(token)
        if local_info is not None and local_info.resource_type == resource_type:
            ResourceGuard._reservations_by_task.pop(token, None)
            return True
        if local_info is not None:
            # Wrong resource_type — not a match
            return False

        client = await self._get_async_redis()
        if client is None:
            return False

        try:
            if self._lua_release_sha is None:
                self._lua_release_sha = await client.script_load(_LUA_RELEASE_RESERVATION_V2)

            zset_key = self._zset_key(resource_type)
            meta_key = self._meta_key(resource_type, token)

            result = await client.evalsha(
                self._lua_release_sha,
                2,
                zset_key,
                meta_key,
                token,
                owner_token,
                str(generation),
                str(int(time.time())),
            )
            return result == "OK"
        except Exception as exc:
            logger.warning("Redis reservation release error: %s", exc)
            return False
        finally:
            if client:
                await client.aclose()

    # ── Orphan reconciler ──

    async def _run_orphan_reconciler_once(self) -> int:
        """Run one pass of the orphan reconciler. Returns count of released orphans."""
        total = 0
        for resource_type in ("import_pipeline", "image_pipeline", "excel_pipeline"):
            client = await self._get_async_redis()
            if client is None:
                continue
            try:
                if self._lua_reaper_sha is None:
                    self._lua_reaper_sha = await client.script_load(_LUA_REAPER_RESERVATIONS_V2)

                zset_key = self._zset_key(resource_type)
                meta_prefix = self._meta_prefix(resource_type)

                count = await client.evalsha(
                    self._lua_reaper_sha,
                    2,
                    zset_key,
                    meta_prefix,
                    str(int(time.time())),
                )
                count = int(count) if count else 0
                if count > 0:
                    logger.warning(
                        "Orphan reconciler released %d expired %s reservations",
                        count, resource_type,
                    )
                total += count
            except Exception as exc:
                logger.debug("Orphan reconciler error for %s: %s", resource_type, exc)
            finally:
                await client.aclose()
        return total

    async def start_orphan_reconciler(self, interval_sec: int = 300) -> None:
        """Start background orphan reconciler loop."""
        if self._orphan_reconciler_task is not None:
            return

        async def _loop():
            while True:
                try:
                    await asyncio.sleep(interval_sec)
                    await self._run_orphan_reconciler_once()
                except asyncio.CancelledError:
                    break
                except Exception as exc:
                    logger.exception("Orphan reconciler crashed: %s", exc)

        self._orphan_reconciler_task = asyncio.create_task(_loop())

    async def stop_orphan_reconciler(self) -> None:
        """Stop orphan reconciler background loop."""
        if self._orphan_reconciler_task is None:
            return
        self._orphan_reconciler_task.cancel()
        try:
            await self._orphan_reconciler_task
        except asyncio.CancelledError:
            pass
        self._orphan_reconciler_task = None

    # ── Async context manager (preferred API) ──

    @asynccontextmanager
    async def acquire_pipeline(
        self,
        resource_type: str = "import_pipeline",
        task_id: str = "",
        owner_token: str = "",
        generation: int = 0,
        ttl_sec: int | None = None,
        *,
        timeout: float = 5.0,
    ):
        """Async context manager for pipeline admission.

        Acquires a reservation slot using the ZSET-based system.
        Yields the reservation token (str) on success, None on failure.
        Automatically releases on exit, exception, or cancellation.
        """
        token: str | None = None
        try:
            token = await asyncio.wait_for(
                self.acquire_reservation(
                    resource_type=resource_type,
                    task_id=task_id,
                    owner_token=owner_token,
                    generation=generation,
                    ttl_sec=ttl_sec,
                ),
                timeout=timeout,
            )
            yield token
        except TimeoutError:
            yield None
        finally:
            if token:
                await self.release_reservation(
                    token,
                    resource_type=resource_type,
                    owner_token=owner_token,
                    generation=generation,
                )

    # ── System-level check ──

    def can_accept_work(self) -> tuple[bool, str | None]:
        """Check if the server can accept new pipeline work.

        Returns (True, None) if OK, or (False, reason) if resource pressure.
        System-level checks only (RSS, memory, lag, temp disk).
        Does NOT check Redis — that is handled by acquire_reservation().
        """
        metrics = self._metrics_provider()

        if metrics.rss_mb > self._thresholds.max_rss_mb:
            return False, f"RSS {metrics.rss_mb:.0f}MB exceeds limit {self._thresholds.max_rss_mb}MB"

        if metrics.available_memory_mb > 0 and metrics.available_memory_mb < self._thresholds.min_available_memory_mb:
            return False, f"Available memory {metrics.available_memory_mb:.0f}MB below minimum {self._thresholds.min_available_memory_mb}MB"

        if metrics.event_loop_lag_ms > self._thresholds.max_event_loop_lag_ms:
            return False, f"Event loop lag {metrics.event_loop_lag_ms:.0f}ms exceeds limit {self._thresholds.max_event_loop_lag_ms}ms"

        if metrics.temp_disk_usage_mb > self._thresholds.max_temp_disk_mb:
            return False, f"Temp disk {metrics.temp_disk_usage_mb:.0f}MB exceeds limit {self._thresholds.max_temp_disk_mb}MB"

        return True, None

    # ── Pipeline count tracking (legacy sync compat — delegates to async) ──

    def increment_pipeline_count(self) -> bool:
        """Legacy: in-process only fallback. Prefer acquire_reservation()."""
        current = ResourceGuard._active_pipeline_count
        if current >= self._thresholds.max_active_pipelines:
            return False
        ResourceGuard._active_pipeline_count += 1
        return True

    def decrement_pipeline_count(self) -> None:
        """Legacy: in-process only fallback. Prefer release_reservation()."""
        ResourceGuard._active_pipeline_count = max(
            0, ResourceGuard._active_pipeline_count - 1
        )

    _active_pipeline_count: int = 0

    # ── System metrics ──

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
        return m

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
