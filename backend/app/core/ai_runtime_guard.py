"""Runtime admission control for expensive AI calls.

The guard intentionally lives below feature services so every OpenAI-compatible
call gets the same protection: bounded concurrency, queue-wait timeout,
per-user fixed-window rate limiting and a provider-endpoint circuit breaker.

Redis is used for the per-user limiter when available so limits are shared by
all web workers. Development can fall back to an in-process bucket; restricted
production deployments fail closed if the Redis limiter cannot be reached.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.core.deployment_profile import DeploymentProfile, detect_deployment_profile
from app.core.log_context import get_log_context

logger = logging.getLogger("postgraduate-ai.ai_guard")


class AIResourceRejectedError(RuntimeError):
    """Raised when an AI call is rejected before contacting the provider."""

    def __init__(self, reason: str, *, retry_after_sec: int | None = None) -> None:
        self.reason = reason
        self.retry_after_sec = retry_after_sec
        super().__init__(reason)


@dataclass
class _CircuitState:
    state: str = "closed"  # closed | open | half_open
    failures: int = 0
    opened_at: float = 0.0
    probe_in_flight: bool = False


class AIRuntimeGuard:
    def __init__(self) -> None:
        self._sem_lock = threading.Lock()
        self._semaphores: dict[
            int, tuple[asyncio.AbstractEventLoop, asyncio.Semaphore]
        ] = {}

        self._state_lock = threading.Lock()
        self._circuits: dict[str, _CircuitState] = {}
        self._local_rate: dict[tuple[str, int], int] = {}
        self._redis_pool: Any = None

        self._metrics: dict[str, int | float] = {
            "requests": 0,
            "success": 0,
            "failures": 0,
            "rejected_rate_limit": 0,
            "rejected_overload": 0,
            "rejected_circuit": 0,
            "rejected_prompt_too_large": 0,
            "tokens": 0,
            "in_flight": 0,
            "queue_wait_ms_total": 0.0,
            "queue_wait_count": 0,
            "circuit_trips": 0,
        }

    # ------------------------------------------------------------------
    # Environment / Redis
    # ------------------------------------------------------------------

    @staticmethod
    def _restricted() -> bool:
        if str(settings.APP_ENV).strip().lower() == "production":
            return True
        try:
            return detect_deployment_profile() == DeploymentProfile.CLOUD_API
        except Exception:
            return True

    async def _redis(self):
        if not settings.REDIS_URL:
            return None
        try:
            import redis.asyncio as redis_async

            if self._redis_pool is None:
                self._redis_pool = redis_async.ConnectionPool.from_url(
                    settings.REDIS_URL,
                    socket_connect_timeout=1.5,
                    socket_timeout=1.5,
                    decode_responses=True,
                    max_connections=max(4, int(settings.AI_MAX_CONCURRENCY) * 2),
                )
            return redis_async.Redis(connection_pool=self._redis_pool)
        except Exception:
            return None

    async def close(self) -> None:
        pool = self._redis_pool
        self._redis_pool = None
        if pool is not None:
            try:
                await pool.aclose()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Concurrency
    # ------------------------------------------------------------------

    def _semaphore(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        key = id(loop)
        with self._sem_lock:
            for old_key in [
                k
                for k, (old_loop, _) in self._semaphores.items()
                if old_loop.is_closed()
            ]:
                self._semaphores.pop(old_key, None)
            entry = self._semaphores.get(key)
            if entry is None:
                sem = asyncio.Semaphore(max(1, int(settings.AI_MAX_CONCURRENCY)))
                self._semaphores[key] = (loop, sem)
                return sem
            return entry[1]

    async def acquire_slot(self) -> tuple[asyncio.Semaphore, float]:
        sem = self._semaphore()
        started = time.perf_counter()
        try:
            await asyncio.wait_for(
                sem.acquire(),
                timeout=max(0.05, float(settings.AI_QUEUE_WAIT_TIMEOUT_SEC)),
            )
        except TimeoutError as exc:
            with self._state_lock:
                self._metrics["rejected_overload"] = (
                    int(self._metrics["rejected_overload"]) + 1
                )
            raise AIResourceRejectedError(
                "ai_overloaded",
                retry_after_sec=max(1, int(settings.AI_QUEUE_WAIT_TIMEOUT_SEC)),
            ) from exc

        wait_ms = (time.perf_counter() - started) * 1000
        with self._state_lock:
            self._metrics["in_flight"] = int(self._metrics["in_flight"]) + 1
            self._metrics["queue_wait_ms_total"] = (
                float(self._metrics["queue_wait_ms_total"]) + wait_ms
            )
            self._metrics["queue_wait_count"] = (
                int(self._metrics["queue_wait_count"]) + 1
            )
        return sem, wait_ms

    def release_slot(self, sem: asyncio.Semaphore) -> None:
        sem.release()
        with self._state_lock:
            self._metrics["in_flight"] = max(0, int(self._metrics["in_flight"]) - 1)

    # ------------------------------------------------------------------
    # Per-user rate limit
    # ------------------------------------------------------------------

    def _subject(self) -> str | None:
        ctx = get_log_context()
        user_id = ctx.get("user_id")
        if user_id not in (None, "", "-"):
            return f"u:{user_id}"
        admin_id = ctx.get("admin_id")
        if admin_id not in (None, "", "-"):
            return f"a:{admin_id}"
        return None

    def _local_rate_allowed(self, subject: str, now: float) -> tuple[bool, int]:
        limit = max(0, int(settings.AI_USER_RPM_LIMIT))
        if limit <= 0:
            return True, 0
        window = int(now // 60)
        key = (subject, window)
        with self._state_lock:
            # Keep at most the current and previous minute to avoid unbounded growth.
            for old_key in [k for k in self._local_rate if k[1] < window - 1]:
                self._local_rate.pop(old_key, None)
            count = self._local_rate.get(key, 0) + 1
            self._local_rate[key] = count
        retry_after = max(1, 60 - int(now % 60))
        return count <= limit, retry_after

    async def enforce_rate_limit(self) -> None:
        subject = self._subject()
        limit = max(0, int(settings.AI_USER_RPM_LIMIT))
        if subject is None or limit <= 0:
            return

        now = time.time()
        client = await self._redis()
        if client is None and self._restricted() and settings.AI_RATE_LIMIT_FAIL_CLOSED:
            with self._state_lock:
                self._metrics["rejected_rate_limit"] = (
                    int(self._metrics["rejected_rate_limit"]) + 1
                )
            raise AIResourceRejectedError(
                "ai_rate_limit_unavailable", retry_after_sec=5
            )

        if client is not None:
            window = int(now // 60)
            env = str(settings.APP_ENV or "unknown").strip().lower()
            key = f"memograd:{env}:ai:rate:{window}:{subject}"
            try:
                pipe = client.pipeline(transaction=True)
                pipe.incr(key)
                pipe.expire(key, 70)
                result = await pipe.execute()
                count = int(result[0])
                if count <= limit:
                    return
                retry_after = max(1, 60 - int(now % 60))
                with self._state_lock:
                    self._metrics["rejected_rate_limit"] = (
                        int(self._metrics["rejected_rate_limit"]) + 1
                    )
                raise AIResourceRejectedError(
                    "ai_rate_limited", retry_after_sec=retry_after
                )
            except AIResourceRejectedError:
                raise
            except Exception as exc:
                if self._restricted() and settings.AI_RATE_LIMIT_FAIL_CLOSED:
                    with self._state_lock:
                        self._metrics["rejected_rate_limit"] = (
                            int(self._metrics["rejected_rate_limit"]) + 1
                        )
                    raise AIResourceRejectedError(
                        "ai_rate_limit_unavailable", retry_after_sec=5
                    ) from exc
                logger.debug(
                    "AI Redis rate limiter unavailable; using local fallback: %s", exc
                )

        allowed, retry_after = self._local_rate_allowed(subject, now)
        if not allowed:
            with self._state_lock:
                self._metrics["rejected_rate_limit"] = (
                    int(self._metrics["rejected_rate_limit"]) + 1
                )
            raise AIResourceRejectedError(
                "ai_rate_limited", retry_after_sec=retry_after
            )

    # ------------------------------------------------------------------
    # Circuit breaker
    # ------------------------------------------------------------------

    def assert_circuit_available(self, endpoint_key: str) -> None:
        now = time.monotonic()
        recovery = max(1.0, float(settings.AI_CIRCUIT_RECOVERY_SEC))
        with self._state_lock:
            state = self._circuits.setdefault(endpoint_key, _CircuitState())
            if state.state == "closed":
                return
            if state.state == "open" and (now - state.opened_at) >= recovery:
                state.state = "half_open"
                state.probe_in_flight = True
                return
            if state.state == "half_open" and not state.probe_in_flight:
                state.probe_in_flight = True
                return
            self._metrics["rejected_circuit"] = (
                int(self._metrics["rejected_circuit"]) + 1
            )
        raise AIResourceRejectedError(
            "ai_circuit_open",
            retry_after_sec=max(1, int(recovery)),
        )

    def record_provider_success(self, endpoint_key: str) -> None:
        with self._state_lock:
            state = self._circuits.setdefault(endpoint_key, _CircuitState())
            state.state = "closed"
            state.failures = 0
            state.opened_at = 0.0
            state.probe_in_flight = False

    def record_provider_failure(self, endpoint_key: str, *, retryable: bool) -> None:
        with self._state_lock:
            state = self._circuits.setdefault(endpoint_key, _CircuitState())
            if not retryable:
                # The endpoint is reachable; 4xx configuration/input failures do
                # not indicate provider availability problems.
                if state.state == "half_open":
                    state.state = "closed"
                    state.failures = 0
                    state.probe_in_flight = False
                return

            state.failures += 1
            threshold = max(1, int(settings.AI_CIRCUIT_FAILURE_THRESHOLD))
            should_open = state.state == "half_open" or state.failures >= threshold
            if should_open:
                was_open = state.state == "open"
                state.state = "open"
                state.opened_at = time.monotonic()
                state.probe_in_flight = False
                if not was_open:
                    self._metrics["circuit_trips"] = (
                        int(self._metrics["circuit_trips"]) + 1
                    )

    # ------------------------------------------------------------------
    # Request cost guard / metrics
    # ------------------------------------------------------------------

    def validate_prompt(self, prompt_chars: int) -> None:
        maximum = max(0, int(settings.AI_MAX_PROMPT_CHARS))
        if maximum > 0 and prompt_chars > maximum:
            with self._state_lock:
                self._metrics["rejected_prompt_too_large"] = (
                    int(self._metrics["rejected_prompt_too_large"]) + 1
                )
            raise AIResourceRejectedError("ai_prompt_too_large")

    def bounded_max_tokens(self, requested: int | None) -> int | None:
        cap = max(0, int(settings.AI_SINGLE_MAX_TOKENS))
        if cap <= 0:
            return requested
        if requested is None:
            return cap
        return min(max(1, int(requested)), cap)

    def record_request(self) -> None:
        with self._state_lock:
            self._metrics["requests"] = int(self._metrics["requests"]) + 1

    def record_success(self, tokens: int) -> None:
        with self._state_lock:
            self._metrics["success"] = int(self._metrics["success"]) + 1
            self._metrics["tokens"] = int(self._metrics["tokens"]) + max(0, int(tokens))

    def record_failure(self) -> None:
        with self._state_lock:
            self._metrics["failures"] = int(self._metrics["failures"]) + 1

    def metrics_snapshot(self) -> dict[str, int | float]:
        with self._state_lock:
            result = dict(self._metrics)
            result["open_circuits"] = sum(
                1 for state in self._circuits.values() if state.state == "open"
            )
            wait_count = max(1, int(result["queue_wait_count"]))
            result["queue_wait_ms_avg"] = (
                float(result["queue_wait_ms_total"]) / wait_count
            )
            return result


ai_runtime_guard = AIRuntimeGuard()
