"""PaddleXHttpOcrWorkerClient — OCR via Windows PaddleX General OCR Basic Serving.

Sends Base64-encoded page images to a remote PaddleX HTTP endpoint and maps
the response to the standard ``WorkerResult`` schema.

Design:
- Uses ``httpx.AsyncClient`` (no blocking I/O).
- ``asyncio.Semaphore`` enforces a max-concurrency cap (default 1 for RTX 3050
  4 GB).
- Retry with exponential backoff + jitter + deadline for transient failures.
- Thread-safe circuit breaker (``asyncio.Lock``) with single half-open probe.
- Pre-request size checks and streamed response with size budget.
- Recognise / recognise_batch implement the ``OcrWorkerClient`` protocol.
- Every response is validated; broken data degrades per-field, not per-page.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import random
import re
import time
import uuid
from datetime import UTC
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from app.core.config import settings
from app.core.log_context import get_trace_headers
from app.core.ocr_runtime_config import (
    OcrRuntimeConfig,
    sanitize_url,
    sanitize_url_strip_credentials,
)
from app.core.ocr_types import STABLE_ERROR_CODES, WorkerResult
from app.services.ocr_distributed_concurrency import (
    DistributedConcurrencyError,
    get_global_concurrency,
)

logger = logging.getLogger(__name__)

# Allowlist for auth header names — prevents arbitrary header injection
_VALID_HEADER_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# ── Retry configuration ─────────────────────────────────────────────────────

_RETRYABLE_HTTP_STATUSES = frozenset({429, 502, 503, 504})
_RETRY_MAX = 3
_RETRY_BASE_DELAY: float = 1.0
_RETRY_MAX_DELAY: float = 30.0
_RETRY_JITTER: float = 0.1


def _is_retryable_status(status_code: int) -> bool:
    return status_code in _RETRYABLE_HTTP_STATUSES


def _is_retryable_exception(exc: Exception) -> bool:
    """Return True for transient httpx failures that warrant a retry.

    Matches the retryable set documented on the request path: ConnectError,
    ReadTimeout, WriteError. HTTP 429/502/503/504 are handled separately via
    ``_is_retryable_status``.
    """
    return isinstance(
        exc,
        (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteError),
    )


def _compute_backoff(
    attempt: int,
    *,
    base_delay: float = _RETRY_BASE_DELAY,
    max_delay: float = _RETRY_MAX_DELAY,
    jitter: float = _RETRY_JITTER,
    retry_after: float | None = None,
) -> float:
    """Compute exponential backoff with optional Retry-After override.

    ``attempt`` is 0-based (first retry = 0).
    """
    if retry_after is not None and retry_after > 0:
        return min(retry_after, max_delay)
    delay = min(base_delay * (2**attempt), max_delay)
    jitter_amount = delay * jitter
    return delay + random.uniform(-jitter_amount, jitter_amount)


_RETRY_AFTER_SECONDS_RE = re.compile(r"^\s*(\d+)\s*$")
_RETRY_AFTER_DATE_RE = re.compile(
    r"^\s*(Mon|Tue|Wed|Thu|Fri|Sat|Sun), "
    r"\d{2} (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{4} "
    r"\d{2}:\d{2}:\d{2} (GMT|UTC)\s*$"
)


def _parse_retry_after(response: httpx.Response) -> float | None:
    """Parse Retry-After header, returning delay in seconds or None."""
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    raw = raw.strip()

    # Seconds format
    m = _RETRY_AFTER_SECONDS_RE.match(raw)
    if m:
        return float(m.group(1))

    # HTTP-date format
    try:
        parsed = parsedate_to_datetime(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return max(0.0, parsed.timestamp() - time.time())
    except (TypeError, ValueError, OverflowError):
        pass

    return None


def _compute_base64_size(raw_bytes: int) -> int:
    """Return the exact Base64 payload size for *raw_bytes*."""
    return 4 * ((max(0, raw_bytes) + 2) // 3)


def _compute_engine_fingerprint(config: OcrRuntimeConfig) -> str:
    """Build a stable engine fingerprint for provenance tracking."""
    raw = (
        f"backend=paddlex_http|"
        f"endpoint={sanitize_url_strip_credentials(config.remote_url)}|"
        f"version=1|"
        f"connect_timeout={config.remote_connect_timeout_sec}|"
        f"read_timeout={config.remote_read_timeout_sec}|"
        f"det_thresh={config.det_db_thresh}|"
        f"box_thresh={config.det_db_box_thresh}|"
        f"unclip={config.det_db_unclip_ratio}|"
        f"drop={config.drop_score}"
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _encode_base64_ascii(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _encode_json_body(payload: dict[str, Any]) -> bytes:
    """Serialize a potentially large request body off the event-loop thread."""
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


async def _read_limited_response(
    response: httpx.Response,
    limit: int,
) -> tuple[bytes, bool]:
    """Read a streamed response with a hard memory bound.

    Returns ``(body, exceeded)``.  When ``limit <= 0`` the response is read
    without an application-level cap.
    """
    buffer = bytearray()
    async for chunk in response.aiter_bytes():
        if limit > 0 and len(buffer) + len(chunk) > limit:
            remaining = max(0, limit - len(buffer))
            if remaining:
                buffer.extend(chunk[:remaining])
            return bytes(buffer), True
        buffer.extend(chunk)
    return bytes(buffer), False


class PaddleXHttpOcrWorkerClient:
    """HTTP client for the PaddleX General OCR Basic Serving API.

    Includes circuit breaker: after ``_circuit_failure_threshold`` consecutive
    failures, the circuit opens and all calls are fast-rejected for
    ``_circuit_recovery_timeout`` seconds, then a single probe (half-open)
    determines whether to close the circuit again.

    Retry with exponential backoff + jitter for transient failures
    (ConnectError, ReadTimeout, WriteError, HTTP 429/502/503/504).
    """

    # Circuit breaker defaults (per-instance config, 5 failures / 30s recovery)
    _circuit_failure_threshold: int = 5
    _circuit_recovery_timeout: float = 30.0

    def __init__(
        self,
        config: OcrRuntimeConfig,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._config = config
        self._closed = False
        self._fingerprint = _compute_engine_fingerprint(config)
        self._semaphore = asyncio.Semaphore(config.remote_max_concurrency)
        self._batch_concurrency = max(1, int(config.remote_max_concurrency))
        self._health_url = _derive_health_url(config.remote_url)

        # Remote auth — validate header name to prevent injection
        auth_header = config.remote_auth_header or "Authorization"
        if not _VALID_HEADER_NAME_RE.match(auth_header):
            raise ValueError(
                f"Invalid OCR auth header name: {auth_header!r}. "
                "Must match [A-Za-z0-9_-]+"
            )
        self._auth_header = auth_header
        self._auth_scheme = config.remote_auth_scheme or "Bearer"
        self._auth_token = config.remote_auth_token

        # Circuit breaker state
        self._circuit_state = "closed"  # closed | open | half-open
        self._circuit_failures = 0
        self._circuit_last_failure = 0.0
        self._circuit_last_success = 0.0
        self._circuit_total_trips = 0
        self._circuit_lock = asyncio.Lock()
        self._half_open_probe_in_flight = False

        # Metrics
        self._metrics = {
            "backend": "paddlex_http",
            "configured": True,
            "accepted": 0,
            "queued": 0,
            "running": 0,
            "finished": 0,
            "failed": 0,
            "timed_out": 0,
            "connection_errors": 0,
            "http_errors": 0,
            "protocol_errors": 0,
            "service_errors": 0,
            "circuit_breaker_rejected": 0,
            "circuit_breaker_trips": 0,
            "circuit_state": "closed",
            "max_concurrency": config.remote_max_concurrency,
            "last_success_time": 0.0,
            "last_error_code": "",
            "last_health_check_time": 0.0,
            "reachable": False,
            "endpoint": sanitize_url(config.remote_url),
            "retry_count": 0,
            "response_aborted": 0,
            "request_size_rejected": 0,
        }

        if http_client is not None:
            self._client = http_client
            self._http_client_owned = False
        else:
            timeout = httpx.Timeout(
                connect=config.remote_connect_timeout_sec,
                read=config.remote_read_timeout_sec,
                write=config.remote_connect_timeout_sec,
                pool=config.remote_connect_timeout_sec,
            )
            limits = httpx.Limits(
                max_keepalive_connections=config.remote_max_concurrency,
                max_connections=config.remote_max_concurrency,
            )
            self._client = httpx.AsyncClient(timeout=timeout, limits=limits)
            self._http_client_owned = True

    # ── Public API ────────────────────────────────────────────────────────────

    async def recognize(
        self,
        image_bytes: bytes,
        page_index: int = 0,
        *,
        mode: str = "boxes",
        options: dict | None = None,
    ) -> WorkerResult:
        """Recognise a single page."""
        if self._closed:
            return self._make_error(
                page_index,
                STABLE_ERROR_CODES["REMOTE_CLOSED"],
                "Client is shut down",
            )

        self._metrics["accepted"] += 1

        # Reject invalid/oversized input before reserving local or distributed
        # capacity. These are caller-side failures and must not trip the remote
        # circuit breaker.
        if not image_bytes:
            self._metrics["failed"] += 1
            self._metrics["request_size_rejected"] += 1
            return self._make_error(
                page_index,
                STABLE_ERROR_CODES["REMOTE_PROTOCOL_ERROR"],
                "Image payload is empty",
            )
        max_req_bytes = self._config.remote_request_max_bytes
        if max_req_bytes > 0 and len(image_bytes) > max_req_bytes:
            self._metrics["failed"] += 1
            self._metrics["request_size_rejected"] += 1
            encoded_size = _compute_base64_size(len(image_bytes))
            return self._make_error(
                page_index,
                STABLE_ERROR_CODES["REMOTE_PROTOCOL_ERROR"],
                f"Image too large: {len(image_bytes)} raw bytes "
                f"(about {encoded_size} Base64 bytes) exceeds "
                f"{max_req_bytes} raw-byte limit",
            )

        # Circuit breaker — fast sync check first, then async with lock
        half_open_probe = False
        if not self._circuit_may_attempt():
            allowed = await self._circuit_may_attempt_async()
            if not allowed:
                self._metrics["failed"] += 1
                self._metrics["circuit_breaker_rejected"] += 1
                return self._make_error(
                    page_index,
                    STABLE_ERROR_CODES["REMOTE_CIRCUIT_OPEN"],
                    f"OCR circuit breaker open "
                    f"(failures={self._circuit_failures}, "
                    f"recovery in {max(0.0, self._circuit_recovery_timeout - (time.time() - self._circuit_last_failure)):.0f}s)",
                )
            half_open_probe = True

        request_id = uuid.uuid4().hex[:16]
        start = time.monotonic()
        dist_guard: Any = None
        dist_token: str | None = None
        acquired_local = False
        backend_attempted = False
        result: WorkerResult

        # Acquire local capacity first.  Reserving the distributed slot while
        # waiting behind the local semaphore wastes global capacity and lets the
        # lease expire before the request even starts.
        self._metrics["queued"] += 1
        try:
            queue_budget = min(
                float(self._config.queue_wait_timeout),
                float(self._config.total_deadline),
            )
            await asyncio.wait_for(
                self._semaphore.acquire(),
                timeout=max(0.001, queue_budget),
            )
            acquired_local = True
            self._metrics["queued"] = max(0, self._metrics["queued"] - 1)
            self._metrics["running"] += 1

            try:
                dist_guard = get_global_concurrency()
                dist_token = await dist_guard.acquire_global()
                if dist_token is None:
                    result = self._make_error(
                        page_index,
                        STABLE_ERROR_CODES["QUEUE_FULL"],
                        "Global OCR concurrency is at capacity",
                    )
                else:
                    remaining = self._config.total_deadline - (time.monotonic() - start)
                    if remaining <= 0:
                        raise TimeoutError
                    backend_attempted = True
                    result = await asyncio.wait_for(
                        self._run_with_distributed_lease(
                            image_bytes=image_bytes,
                            page_index=page_index,
                            request_id=request_id,
                            options=options,
                            dist_guard=dist_guard,
                            dist_token=dist_token,
                        ),
                        timeout=remaining,
                    )
            except DistributedConcurrencyError as exc:
                logger.error("Distributed OCR concurrency unavailable: %s", exc)
                result = self._make_error(
                    page_index,
                    STABLE_ERROR_CODES["ENGINE_NOT_AVAILABLE"],
                    "Distributed OCR concurrency unavailable",
                )
            except TimeoutError:
                self._metrics["timed_out"] += 1
                result = self._make_error(
                    page_index,
                    STABLE_ERROR_CODES["REMOTE_TIMEOUT"],
                    f"OCR total deadline ({self._config.total_deadline}s) exceeded",
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Distributed OCR execution failed")
                result = self._make_error(
                    page_index,
                    STABLE_ERROR_CODES["ENGINE_NOT_AVAILABLE"],
                    f"OCR execution unavailable: {exc}",
                )
        except TimeoutError:
            self._metrics["queued"] = max(0, self._metrics["queued"] - 1)
            result = self._make_error(
                page_index,
                STABLE_ERROR_CODES["QUEUE_TIMEOUT"],
                f"Local OCR queue wait exceeded {self._config.queue_wait_timeout}s",
            )
        except asyncio.CancelledError:
            if not acquired_local:
                self._metrics["queued"] = max(0, self._metrics["queued"] - 1)
            self._metrics["failed"] += 1
            if half_open_probe:
                await self._abandon_half_open_probe()
            raise
        finally:
            if dist_token is not None:
                try:
                    await dist_guard.release_global(dist_token)
                except Exception:
                    pass
            if acquired_local:
                self._metrics["running"] = max(0, self._metrics["running"] - 1)
                self._semaphore.release()

        elapsed = time.monotonic() - start
        if result.status == "success":
            self._metrics["finished"] += 1
            self._metrics["last_success_time"] = time.time()
            await self._record_success()
            result.started_monotonic = start
            result.finished_monotonic = start + elapsed
        else:
            self._metrics["failed"] += 1
            if backend_attempted:
                await self._record_failure()
            elif half_open_probe:
                await self._abandon_half_open_probe()

        return result

    async def recognize_batch(
        self,
        images: list[tuple[int, bytes]],
        *,
        mode: str = "boxes",
        options: dict | None = None,
    ) -> list[WorkerResult]:
        """Recognise multiple pages concurrently.

        Results are sorted by ``page_index``.  A single-page failure does
        not affect other pages.
        """
        if not images:
            return []

        resolved: list[WorkerResult | None] = [None] * len(images)
        next_pos = 0

        async def _batch_worker() -> None:
            nonlocal next_pos
            while True:
                pos = next_pos
                next_pos += 1
                if pos >= len(images):
                    return
                idx, png = images[pos]
                try:
                    resolved[pos] = await self.recognize(
                        png,
                        page_index=idx,
                        mode=mode,
                        options=options,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    resolved[pos] = self._make_error(
                        idx,
                        STABLE_ERROR_CODES["ENGINE_ERROR"],
                        str(exc) or "Unknown error",
                    )

        workers = [
            asyncio.create_task(_batch_worker())
            for _ in range(min(self._batch_concurrency, len(images)))
        ]
        await asyncio.gather(*workers)

        final = [
            r
            if isinstance(r, WorkerResult)
            else self._make_error(
                images[i][0],
                STABLE_ERROR_CODES["ENGINE_ERROR"],
                "Missing batch result",
            )
            for i, r in enumerate(resolved)
        ]
        final.sort(key=lambda wr: wr.page_index)
        return final

    async def shutdown(
        self,
        *,
        graceful_timeout: float | None = None,
        kill_timeout: float | None = None,
    ) -> None:
        """Graceful shutdown — idempotent."""
        del graceful_timeout, kill_timeout  # HTTP requests are closed by httpx.
        if self._closed:
            return
        self._closed = True
        if self._http_client_owned:
            await self._client.aclose()
        logger.info("PaddleXHttpOcrWorkerClient shut down")

    @property
    def metrics(self) -> dict:
        return dict(self._metrics)

    # ── Internal ──────────────────────────────────────────────────────────────

    # ── Circuit breaker ──

    def _circuit_may_attempt(self) -> bool:
        """Fast sync check — no lock needed for closed state.

        Returns False when the circuit is open or half-open, deferring
        to the async check for thread-safe state transitions.
        """
        if self._circuit_state == "closed":
            return True
        return False

    async def _circuit_may_attempt_async(self) -> bool:
        """Full async check with lock for thread-safe state transitions.

        Only called when the fast check returns False (open or half-open).
        Guarded by ``_circuit_lock`` to prevent race conditions.
        """
        async with self._circuit_lock:
            if self._circuit_state == "closed":
                return True

            if self._circuit_state == "open":
                if (
                    time.time() - self._circuit_last_failure
                    >= self._circuit_recovery_timeout
                ):
                    self._circuit_state = "half-open"
                    self._half_open_probe_in_flight = True  # this request IS the probe
                    self._circuit_failures = 0
                    logger.info("OCR circuit half-open — probing remote endpoint")
                    return True
                return False

            # Half-open: allow exactly one probe
            if self._half_open_probe_in_flight:
                return False
            self._half_open_probe_in_flight = True
            return True

    async def _abandon_half_open_probe(self) -> None:
        """Release a half-open probe reservation that never reached the backend."""
        async with self._circuit_lock:
            if self._circuit_state == "half-open":
                self._half_open_probe_in_flight = False

    async def _record_success(self) -> None:
        """Record a successful OCR call — resets circuit breaker.

        Thread-safe: guarded by ``_circuit_lock``.
        """
        async with self._circuit_lock:
            self._circuit_failures = 0
            self._circuit_last_success = time.time()
            if self._circuit_state == "half-open":
                self._circuit_state = "closed"
                self._half_open_probe_in_flight = False
                logger.info("OCR circuit closed — remote endpoint recovered")
                self._metrics["circuit_state"] = "closed"

    async def _record_failure(self) -> None:
        """Record an OCR failure — may trip circuit breaker.

        Thread-safe: guarded by ``_circuit_lock``.
        In half-open state, a single probe failure immediately re-opens the circuit.
        """
        async with self._circuit_lock:
            self._circuit_failures += 1
            self._circuit_last_failure = time.time()
            threshold = self._circuit_failure_threshold

            # Half-open → probe failure → immediately re-open
            if self._circuit_state == "half-open":
                self._circuit_state = "open"
                self._half_open_probe_in_flight = False
                self._metrics["circuit_state"] = "open"
                logger.warning(
                    "OCR circuit re-OPEN after probe failure (recovery in %.0fs)",
                    self._circuit_recovery_timeout,
                )
                return

            if self._circuit_failures >= threshold:
                was_open = self._circuit_state == "open"
                self._circuit_state = "open"
                self._half_open_probe_in_flight = False
                self._metrics["circuit_state"] = "open"
                if not was_open:
                    self._circuit_total_trips += 1
                    self._metrics["circuit_breaker_trips"] = self._circuit_total_trips
                    logger.warning(
                        "OCR circuit OPEN after %d consecutive failures "
                        "(recovery in %.0fs)",
                        self._circuit_failures,
                        self._circuit_recovery_timeout,
                    )

    # ── Request execution ──

    async def _run_with_distributed_lease(
        self,
        *,
        image_bytes: bytes,
        page_index: int,
        request_id: str,
        options: dict | None,
        dist_guard: Any,
        dist_token: str,
    ) -> WorkerResult:
        """Run OCR while keeping a Redis-backed concurrency lease alive.

        Local fallback tokens do not need renewal.  For Redis tokens, a lost
        lease cancels the in-flight HTTP request so this process cannot keep
        using GPU capacity after another process has legitimately acquired the
        expired slot.
        """
        ocr_task = asyncio.create_task(
            self._do_recognize(image_bytes, page_index, request_id, options)
        )
        if dist_token.startswith("local_"):
            return await ocr_task

        ttl_sec = max(3, int(settings.OCR_DISTRIBUTED_LEASE_SEC))
        renew_task = asyncio.create_task(
            self._renew_distributed_lease(dist_guard, dist_token, ttl_sec)
        )
        try:
            done, _ = await asyncio.wait(
                {ocr_task, renew_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            # Renewal only completes on lease loss or an operational failure.
            if renew_task in done:
                exc = renew_task.exception()
                if exc is not None:
                    raise exc
                raise DistributedConcurrencyError(
                    "Distributed OCR concurrency lease was lost"
                )
            return await ocr_task
        finally:
            for task in (ocr_task, renew_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(ocr_task, renew_task, return_exceptions=True)

    async def _renew_distributed_lease(
        self,
        dist_guard: Any,
        dist_token: str,
        ttl_sec: int,
    ) -> None:
        interval = max(1.0, min(float(ttl_sec) / 3.0, 30.0))
        while True:
            await asyncio.sleep(interval)
            renewed = await dist_guard.renew_global(dist_token, ttl_sec=ttl_sec)
            if not renewed:
                raise DistributedConcurrencyError(
                    "Distributed OCR concurrency lease was lost"
                )

    async def _do_recognize(
        self,
        image_bytes: bytes,
        page_index: int,
        request_id: str,
        options: dict | None,
    ) -> WorkerResult:
        """Send a single page to PaddleX and map the response.

        Includes pre-request size check, retry with backoff, and
        streamed response with size budget enforcement.
        """
        # Build auth + correlation headers
        headers = get_trace_headers()
        if self._auth_token:
            headers[self._auth_header] = f"{self._auth_scheme} {self._auth_token}"

        # The public method enforces the total deadline.  This inner deadline
        # additionally prevents retry/backoff from consuming more than the
        # configured request budget when called directly in tests or tooling.
        deadline = time.monotonic() + float(self._config.total_deadline)

        # Retry loop
        last_exc: BaseException | None = None
        last_status: int | None = None
        last_error_code: str = STABLE_ERROR_CODES["REMOTE_CONNECT_ERROR"]
        retry_count = 0

        for attempt in range(_RETRY_MAX + 1):
            # Check cancellation before each attempt
            t = asyncio.current_task()
            if t is not None and t.cancelled():
                self._metrics["failed"] += 1
                raise asyncio.CancelledError()

            if attempt > 0:
                retry_count += 1

            try:
                result, status_code = await self._do_http_request(
                    image_bytes,
                    page_index,
                    request_id,
                    options,
                    headers,
                )
                self._metrics["retry_count"] = retry_count
                return result
            except _RetryableError as e:
                last_exc = e.__cause__ or e
                last_status = e.status_code
                if e.error_code:
                    last_error_code = e.error_code
                elif last_status and _is_retryable_status(last_status):
                    last_error_code = STABLE_ERROR_CODES["REMOTE_HTTP_ERROR"]
                delay = _compute_backoff(attempt, retry_after=e.retry_after)
                # Cap delay at remaining deadline
                remaining = deadline - time.monotonic()
                if remaining < 0:
                    remaining = 0
                delay = min(delay, remaining)

                if attempt < _RETRY_MAX and remaining > 0:
                    t2 = asyncio.current_task()
                    if t2 is not None and t2.cancelled():
                        raise asyncio.CancelledError()
                    try:
                        await asyncio.sleep(delay)
                    except asyncio.CancelledError:
                        raise
                    t3 = asyncio.current_task()
                    if t3 is not None and t3.cancelled():
                        raise asyncio.CancelledError()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                # Non-retryable — return error immediately
                return self._make_error(
                    page_index,
                    STABLE_ERROR_CODES["REMOTE_HTTP_ERROR"],
                    f"Non-retryable error: {e}",
                )

        # All retries exhausted
        self._metrics["retry_count"] = retry_count
        if last_status and _is_retryable_status(last_status):
            last_error_code = STABLE_ERROR_CODES["REMOTE_HTTP_ERROR"]
        if last_exc is not None:
            return self._make_error(
                page_index,
                last_error_code,
                f"All retries exhausted: {last_exc}",
            )
        return self._make_error(
            page_index,
            last_error_code,
            f"All retries exhausted (HTTP {last_status})"
            if last_status
            else "All retries exhausted",
        )

    async def _do_http_request(
        self,
        image_bytes: bytes,
        page_index: int,
        request_id: str,
        options: dict | None,
        headers: dict[str, str],
    ) -> tuple[WorkerResult, int]:
        """Execute a single HTTP request with streamed response.

        Returns:
            Tuple of (WorkerResult, status_code). On success the WorkerResult
            is a success; on HTTP error it contains the error.

        Raises:
            _RetryableError: transient failure that should be retried.
        """
        b64_data = await asyncio.to_thread(_encode_base64_ascii, image_bytes)

        payload: dict[str, Any] = {
            "file": b64_data,
            "fileType": 1,
        }

        # Threshold mapping from OcrRuntimeConfig
        cfg = self._config
        if cfg.det_db_thresh != 0.2:
            payload["textDetThresh"] = cfg.det_db_thresh
        if cfg.det_db_box_thresh != 0.4:
            payload["textDetBoxThresh"] = cfg.det_db_box_thresh
        if cfg.det_db_unclip_ratio != 1.8:
            payload["textDetUnclipRatio"] = cfg.det_db_unclip_ratio
        if cfg.drop_score != 0.3:
            payload["textRecScoreThresh"] = cfg.drop_score
        if cfg.remote_visualize:
            payload["visualize"] = True
        if cfg.remote_use_doc_orientation_classify:
            payload["useDocOrientationClassify"] = True
        if cfg.remote_use_doc_unwarping:
            payload["useDocUnwarping"] = True
        if cfg.remote_use_textline_orientation:
            payload["useTextlineOrientation"] = True

        request_body = await asyncio.to_thread(_encode_json_body, payload)
        # Do not retain the large Base64 string and payload dict for the entire
        # network round trip; request_body is the only representation needed.
        del b64_data, payload
        request_headers = dict(headers)
        request_headers.setdefault("Content-Type", "application/json")

        try:
            async with self._client.stream(
                "POST",
                cfg.remote_url,
                content=request_body,
                headers=request_headers,
            ) as response:
                status_code = response.status_code

                # Check retryable status BEFORE reading body
                if _is_retryable_status(status_code):
                    retry_after = _parse_retry_after(response)
                    raise _RetryableError(
                        f"Retryable HTTP {status_code}"
                        + (
                            f" (Retry-After: {retry_after:.0f}s)" if retry_after else ""
                        ),
                        status_code=status_code,
                        retry_after=retry_after,
                    )

                if status_code != 200:
                    # Read body for error message (limited)
                    try:
                        body_bytes, truncated = await _read_limited_response(
                            response, 4096
                        )
                        body_text = body_bytes[:500].decode("utf-8", errors="replace")
                        if truncated:
                            body_text += " …(truncated)"
                    except Exception:
                        body_text = f"HTTP {status_code} (body unreadable)"

                    self._metrics["http_errors"] += 1
                    self._metrics["last_error_code"] = STABLE_ERROR_CODES[
                        "REMOTE_HTTP_ERROR"
                    ]
                    return (
                        self._make_error(
                            page_index,
                            STABLE_ERROR_CODES["REMOTE_HTTP_ERROR"],
                            f"HTTP {status_code}: {body_text}",
                        ),
                        status_code,
                    )

                # Stream into a single bytearray so peak memory remains close
                # to the configured response budget (rather than chunks + join).
                max_resp_bytes = cfg.remote_response_max_bytes
                body_bytes, exceeded = await _read_limited_response(
                    response, max_resp_bytes
                )
                if exceeded:
                    self._metrics["response_aborted"] += 1
                    return (
                        self._make_error(
                            page_index,
                            STABLE_ERROR_CODES["REMOTE_PROTOCOL_ERROR"],
                            f"Response exceeded {max_resp_bytes} byte limit",
                        ),
                        status_code,
                    )

        except httpx.ConnectError as exc:
            self._metrics["connection_errors"] += 1
            self._metrics["last_error_code"] = STABLE_ERROR_CODES[
                "REMOTE_CONNECT_ERROR"
            ]
            raise _RetryableError(
                "Connection refused",
                error_code=STABLE_ERROR_CODES["REMOTE_CONNECT_ERROR"],
            ) from exc
        except httpx.TimeoutException as exc:
            self._metrics["timed_out"] += 1
            self._metrics["last_error_code"] = STABLE_ERROR_CODES["REMOTE_TIMEOUT"]
            raise _RetryableError(
                "Request timed out",
                error_code=STABLE_ERROR_CODES["REMOTE_TIMEOUT"],
            ) from exc
        except httpx.ReadError as exc:
            self._metrics["connection_errors"] += 1
            self._metrics["last_error_code"] = STABLE_ERROR_CODES[
                "REMOTE_CONNECT_ERROR"
            ]
            raise _RetryableError(
                "Connection reset",
                error_code=STABLE_ERROR_CODES["REMOTE_CONNECT_ERROR"],
            ) from exc
        except (httpx.WriteError, httpx.RemoteProtocolError) as exc:
            self._metrics["protocol_errors"] += 1
            self._metrics["last_error_code"] = STABLE_ERROR_CODES[
                "REMOTE_PROTOCOL_ERROR"
            ]
            raise _RetryableError(
                "Connection error",
                error_code=STABLE_ERROR_CODES["REMOTE_PROTOCOL_ERROR"],
            ) from exc
        except httpx.RequestError as exc:
            self._metrics["connection_errors"] += 1
            self._metrics["last_error_code"] = STABLE_ERROR_CODES[
                "REMOTE_CONNECT_ERROR"
            ]
            raise _RetryableError(
                "HTTP request failed",
                error_code=STABLE_ERROR_CODES["REMOTE_CONNECT_ERROR"],
            ) from exc
        except _RetryableError:
            raise
        except Exception as exc:
            # Non-retryable exception
            self._metrics["connection_errors"] += 1
            self._metrics["last_error_code"] = STABLE_ERROR_CODES[
                "REMOTE_CONNECT_ERROR"
            ]
            return (
                self._make_error(
                    page_index,
                    STABLE_ERROR_CODES["REMOTE_CONNECT_ERROR"],
                    f"HTTP request failed: {exc}",
                ),
                0,
            )

        # Parse JSON from streamed body
        try:
            body = await asyncio.to_thread(json.loads, body_bytes)
        except Exception as exc:
            self._metrics["protocol_errors"] += 1
            self._metrics["last_error_code"] = STABLE_ERROR_CODES[
                "REMOTE_PROTOCOL_ERROR"
            ]
            return (
                self._make_error(
                    page_index,
                    STABLE_ERROR_CODES["REMOTE_PROTOCOL_ERROR"],
                    f"Non-JSON response: {exc}",
                ),
                status_code,
            )

        # Validate top-level structure
        if not isinstance(body, dict):
            self._metrics["protocol_errors"] += 1
            self._metrics["last_error_code"] = STABLE_ERROR_CODES[
                "REMOTE_PROTOCOL_ERROR"
            ]
            return (
                self._make_error(
                    page_index,
                    STABLE_ERROR_CODES["REMOTE_PROTOCOL_ERROR"],
                    "Response is not a JSON object",
                ),
                status_code,
            )

        error_code = body.get("errorCode", -1)
        if error_code != 0:
            self._metrics["service_errors"] += 1
            self._metrics["last_error_code"] = STABLE_ERROR_CODES[
                "REMOTE_SERVICE_ERROR"
            ]
            error_msg = str(body.get("errorMsg", ""))[:500]
            return (
                self._make_error(
                    page_index,
                    STABLE_ERROR_CODES["REMOTE_SERVICE_ERROR"],
                    f"Service error (code={error_code}): {error_msg}",
                ),
                status_code,
            )

        result_data = body.get("result")
        if not isinstance(result_data, dict):
            self._metrics["protocol_errors"] += 1
            return (
                self._make_error(
                    page_index,
                    STABLE_ERROR_CODES["REMOTE_PROTOCOL_ERROR"],
                    "result is missing or not an object",
                ),
                status_code,
            )

        ocr_results = result_data.get("ocrResults")
        if ocr_results is None:
            ocr_results = []

        if not isinstance(ocr_results, list):
            self._metrics["protocol_errors"] += 1
            return (
                self._make_error(
                    page_index,
                    STABLE_ERROR_CODES["REMOTE_PROTOCOL_ERROR"],
                    "ocrResults is not a list",
                ),
                status_code,
            )

        # Map the first (and typically only) ocrResult to WorkerResult result dict
        mapped_result = _map_pruned_result(
            ocr_results,
            page_index,
            request_id,
            self._fingerprint,
        )

        result = WorkerResult(
            request_id=request_id,
            page_index=page_index,
            status="success",
            result=mapped_result,
            engine_fingerprint=self._fingerprint,
            stable_error_code=None,
            error_type=None,
        )
        return result, status_code

    def _make_error(
        self,
        page_index: int,
        stable_error_code: str,
        error_message: str,
    ) -> WorkerResult:
        self._metrics["last_error_code"] = stable_error_code
        return WorkerResult(
            request_id="",
            page_index=page_index,
            status="failed",
            result={
                "page_index": page_index,
                "text": "",
                "lines": [],
                "boxes": [],
                "confidence": 0.0,
                "transforms": None,
                "coordinate_space": "image",
                "engine_fingerprint": self._fingerprint,
                "failed": True,
                "error": error_message[:1000],
            },
            stable_error_code=stable_error_code,
            error_type=stable_error_code.rsplit(".", 1)[-1]
            if "." in stable_error_code
            else stable_error_code.lower(),
        )


class _RetryableError(Exception):
    """Raised inside ``_do_http_request`` to trigger a retry.

    Attributes:
        status_code: HTTP status code if the error was triggered by an
            HTTP response (e.g. 429, 502).  ``None`` for transport errors.
        error_code: Stable error code for the final error message after
            all retries are exhausted.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: str = "",
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.retry_after = retry_after


# ---------------------------------------------------------------------------
# Response mapping (pure functions — easy to unit test)
# ---------------------------------------------------------------------------


def _derive_health_url(ocr_url: str) -> str:
    """Derive the OpenAPI health URL from the OCR endpoint.

    ``http://host:8080/ocr`` → ``http://host:8080/openapi.json``
    """
    if not ocr_url:
        return ""
    try:
        parsed = __import__("urllib.parse", fromlist=["urlparse"]).urlparse(ocr_url)
        clean = parsed._replace(path="/openapi.json", query="", fragment="")
        return clean.geturl()
    except Exception:
        return ocr_url


def _map_pruned_result(
    ocr_results: list[Any],
    page_index: int,
    request_id: str,
    fingerprint: str,
) -> dict:
    """Convert the first PaddleX ``prunedResult`` into the standard
    ``WorkerResult.result`` dict.
    """
    if not ocr_results:
        return {
            "page_index": page_index,
            "text": "",
            "lines": [],
            "boxes": [],
            "confidence": 0.0,
            "transforms": None,
            "coordinate_space": "image",
            "engine_fingerprint": fingerprint,
            "failed": False,
            "error": None,
        }

    entry = ocr_results[0]
    if not isinstance(entry, dict):
        return _empty_result(page_index, fingerprint)

    pruned = entry.get("prunedResult")
    if not isinstance(pruned, dict):
        return _empty_result(page_index, fingerprint)

    rec_texts = pruned.get("rec_texts")
    rec_scores = pruned.get("rec_scores")
    rec_polys = pruned.get("rec_polys")
    rec_boxes = pruned.get("rec_boxes")

    if not isinstance(rec_texts, list):
        rec_texts = []
    if not isinstance(rec_scores, list):
        rec_scores = []
    if not isinstance(rec_polys, list):
        rec_polys = []
    if not isinstance(rec_boxes, list):
        rec_boxes = []

    text_parts: list[str] = []
    lines: list[dict] = []
    boxes: list[dict] = []
    confidence_sum = 0.0
    valid_conf_count = 0
    degraded_count = 0

    n = max(len(rec_texts), len(rec_scores), len(rec_polys), len(rec_boxes))

    for i in range(n):
        raw_text = _safe_str(rec_texts[i] if i < len(rec_texts) else "")
        if not raw_text:
            continue  # skip empty text (matches existing OcrEngine behaviour)

        text_parts.append(raw_text)

        raw_score = _safe_score(rec_scores[i] if i < len(rec_scores) else None)
        if raw_score is not None:
            confidence_sum += raw_score
            valid_conf_count += 1

        # Polygon
        polygon = _normalize_polygon(rec_polys[i] if i < len(rec_polys) else None)
        if polygon is None:
            degraded_count += 1

        # BBox
        bbox = _normalize_bbox(rec_boxes[i] if i < len(rec_boxes) else None)
        if bbox is None and polygon is not None:
            # Derive bbox from polygon
            xs = polygon[0::2]
            ys = polygon[1::2]
            bbox = [min(xs), min(ys), max(xs), max(ys)]
        elif bbox is not None and polygon is None:
            # Generate polygon from bbox
            polygon = [
                bbox[0],
                bbox[1],
                bbox[2],
                bbox[1],
                bbox[2],
                bbox[3],
                bbox[0],
                bbox[3],
            ]

        line: dict[str, Any] = {
            "text": raw_text,
            "polygon": polygon if polygon is not None else [],
            "bbox": bbox if bbox is not None else [],
            "confidence": raw_score if raw_score is not None else 0.0,
        }
        lines.append(line)

        if bbox is not None:
            boxes.append(
                {
                    "bbox": bbox,
                    "conf": raw_score if raw_score is not None else 0.0,
                }
            )

    avg_confidence = (
        round(confidence_sum / valid_conf_count, 6) if valid_conf_count > 0 else 0.0
    )

    if degraded_count > 0:
        logger.debug(
            "Page %d: %d/%d lines have degraded geometry",
            page_index,
            degraded_count,
            n,
        )

    return {
        "page_index": page_index,
        "text": "\n".join(text_parts),
        "lines": lines,
        "boxes": boxes,
        "confidence": avg_confidence,
        "transforms": None,
        "coordinate_space": "image",
        "engine_fingerprint": fingerprint,
        "failed": False,
        "error": None,
    }


def _empty_result(page_index: int, fingerprint: str) -> dict:
    return {
        "page_index": page_index,
        "text": "",
        "lines": [],
        "boxes": [],
        "confidence": 0.0,
        "transforms": None,
        "coordinate_space": "image",
        "engine_fingerprint": fingerprint,
        "failed": False,
        "error": None,
    }


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _safe_score(value: Any) -> float | None:
    if value is None:
        return None
    try:
        v = float(value)
    except (ValueError, TypeError):
        return None
    if not _isfinite(v):
        return None
    return max(0.0, min(1.0, v))


def _isfinite(v: float) -> bool:
    import math

    return math.isfinite(v)


def _normalize_polygon(poly: Any) -> list[float] | None:
    """Normalise a polygon to ``[x0,y0,x1,y1,x2,y2,x3,y3]``.

    Accepted shapes:
    - ``[[x,y],[x,y],[x,y],[x,y]]``  (nested list)
    - ``[x0,y0,x1,y1,...,x3,y3]``    (flat list, ≥8 values)
    """
    if poly is None:
        return None
    if not isinstance(poly, (list, tuple)):
        return None

    result: list[float] = []

    # Nested: [[x,y], ...]
    if poly and isinstance(poly[0], (list, tuple)):
        for pt in poly[:4]:  # at most 4 points
            if not isinstance(pt, (list, tuple)) or len(pt) < 2:
                return None
            x, y = pt[0], pt[1]
            try:
                result.append(float(x))
                result.append(float(y))
            except (ValueError, TypeError):
                return None
        if len(result) >= 8:
            return _clamp_coords(result)
        return None

    # Flat: [x0,y0,x1,y1,...]
    if not all(isinstance(v, (int, float)) for v in poly[:8]):
        return None
    for v in poly[:8]:
        try:
            result.append(float(v))
        except (ValueError, TypeError):
            return None
    if len(result) >= 8:
        return _clamp_coords(result)
    return None


def _normalize_bbox(bbox: Any) -> list[float] | None:
    """Normalise a bbox to ``[xmin, ymin, xmax, ymax]``."""
    if bbox is None:
        return None
    if not isinstance(bbox, (list, tuple)):
        return None
    if len(bbox) < 4:
        return None
    try:
        vals = [float(v) for v in bbox[:4]]
    except (ValueError, TypeError):
        return None
    if not all(_isfinite(v) for v in vals):
        return None
    return [
        min(vals[0], vals[2]),
        min(vals[1], vals[3]),
        max(vals[0], vals[2]),
        max(vals[1], vals[3]),
    ]


def _clamp_coords(coords: list[float]) -> list[float]:
    """Replace NaN / Inf with 0.0."""
    return [0.0 if not _isfinite(v) else v for v in coords]


async def health_check(
    client: PaddleXHttpOcrWorkerClient,
) -> dict:
    """Check whether the remote PaddleX service is reachable.

    Sends a lightweight GET to ``<scheme>://<host>:<port>/openapi.json``.
    Does **not** trigger GPU inference.  Uses the client's own
    ``AsyncClient`` so that callers can provide a mock transport for tests.
    """
    if not client._health_url:
        return {"reachable": False, "error": "No health URL configured"}

    try:
        headers = get_trace_headers()
        if client._auth_token:
            headers[client._auth_header] = f"{client._auth_scheme} {client._auth_token}"
        resp = await client._client.get(
            client._health_url,
            timeout=httpx.Timeout(client._config.remote_health_timeout_sec),
            headers=headers,
        )
        ok = resp.status_code < 500
        client._metrics["reachable"] = ok
        client._metrics["last_health_check_time"] = time.time()
        if ok:
            client._metrics["last_success_time"] = time.time()
        else:
            client._metrics["last_error_code"] = STABLE_ERROR_CODES["REMOTE_HTTP_ERROR"]
        return {
            "reachable": ok,
            "status_code": resp.status_code,
            "error": None,
        }
    except httpx.ConnectError as exc:
        client._metrics["reachable"] = False
        client._metrics["last_error_code"] = STABLE_ERROR_CODES["REMOTE_CONNECT_ERROR"]
        client._metrics["last_health_check_time"] = time.time()
        return {"reachable": False, "error": f"Connection refused: {exc}"}
    except httpx.TimeoutException as exc:
        client._metrics["reachable"] = False
        client._metrics["last_error_code"] = STABLE_ERROR_CODES["REMOTE_TIMEOUT"]
        client._metrics["last_health_check_time"] = time.time()
        return {"reachable": False, "error": f"Health check timed out: {exc}"}
    except Exception as exc:
        client._metrics["reachable"] = False
        client._metrics["last_error_code"] = STABLE_ERROR_CODES["REMOTE_CONNECT_ERROR"]
        client._metrics["last_health_check_time"] = time.time()
        return {"reachable": False, "error": str(exc)[:300]}
