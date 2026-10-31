"""PaddleOCR-VL API client — async HTTP client for the external OCR service.

API flow:
    1. POST /api/v2/ocr/jobs  (submit image → receive job_id)
    2. GET  /api/v2/ocr/jobs/{job_id}  (poll until done/failed)
    3. Download result from resultUrl.jsonUrl  (JSONL → structured text)
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import random
import socket
import time
import uuid
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from app.core.deployment_profile import DeploymentProfile, detect_deployment_profile
from app.core.log_context import get_trace_headers

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# API contract helpers
# ---------------------------------------------------------------------------

# PaddleOCR-VL API response envelope:
#   {"code": 0, "msg": "Success", "data": {"jobId": "xxx", ...}}
#   {"code": 0, "msg": "Success", "data": {"status": "done", "result": {...}}}
#
# All responses follow this structure.  The helpers below unwrap the envelope
# so callers work with data dict directly.


def _unwrap_data(body: dict) -> dict:
    """Unwrap the ``data`` envelope from a PaddleOCR-VL API response.

    Raises ``JobSubmissionError`` / ``JobPollingError`` when the API
    returns a non-zero code (caller must catch and decide retry).
    """
    code = body.get("code", -1)
    if code != 0:
        msg = body.get("msg") or body.get("message") or "unknown error"
        raise JobSubmissionError(
            f"PaddleOCR-VL API error: code={code} msg={msg} "
            f"body={json.dumps(body, ensure_ascii=False)[:300]}"
        )
    data = body.get("data")
    if not isinstance(data, dict):
        raise JobSubmissionError(
            f"PaddleOCR-VL API response missing 'data' dict: "
            f"{json.dumps(body, ensure_ascii=False)[:200]}"
        )
    return data


def _extract_job_id(data: dict) -> str:
    """Extract the job ID from an unwrapped data dict.

    Tries ``jobId`` (official) then ``job_id`` (fallback).
    Raises ``ContractError`` (non-retriable) when the field is missing.
    """
    job_id = data.get("jobId") or data.get("job_id") or ""
    if not job_id:
        raise ContractError(
            f"No jobId in API response data: "
            f"{json.dumps(data, ensure_ascii=False)[:200]}"
        )
    return str(job_id)


def _raise_on_bad_status(response: httpx.Response) -> None:
    """Raise JobSubmissionError if HTTP status is not 200.

    Passes the status code and Retry-After header (if present) so retry
    logic can distinguish retriable vs non-retriable errors.
    """
    if response.status_code != 200:
        retry_after = _get_retry_after(response)
        raise JobSubmissionError(
            f"PaddleOCR-VL HTTP {response.status_code}",
            status_code=response.status_code,
            retry_after=retry_after,
        )


def _get_retry_after(response: httpx.Response) -> float | None:
    """Extract Retry-After from a response header."""
    val = response.headers.get("Retry-After")
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _parse_json_body(response: httpx.Response) -> dict:
    """Parse JSON response body with error guard."""
    try:
        body = response.json()
    except (json.JSONDecodeError, TypeError) as exc:
        raise JobSubmissionError(
            f"Non-JSON response (HTTP {response.status_code}): {response.text[:200]}"
        ) from exc
    if not isinstance(body, dict):
        raise JobSubmissionError(
            f"Unexpected response type {type(body).__name__}: {str(body)[:200]}"
        )
    return body


def _extract_result_url(job_data: dict) -> str:
    """Extract the result JSON URL from a job data dict.

    Tries multiple field locations in priority order:
      result.jsonUrl → result.url → resultUrl → resultUrl.jsonUrl

    ``job_data`` is the unwrapped data dict (after ``_unwrap_data``).
    """
    result_data = job_data.get("result")
    if isinstance(result_data, dict):
        url = result_data.get("jsonUrl") or result_data.get("url")
        if isinstance(url, str):
            return url

    raw = job_data.get("resultUrl")
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        url = raw.get("jsonUrl") or raw.get("url")
        if isinstance(url, str):
            return url

    raise ResultDownloadError(
        f"No result URL in job data: {json.dumps(job_data, ensure_ascii=False)[:300]}"
    )


_DEFAULT_BASE_URL = "https://paddleocr.aistudio-app.com"
_OCR_VL_API_PATH = "/api/v2/ocr/jobs"  # endpoint path used by urljoin
_DEFAULT_POLL_INTERVAL = 5.0  # seconds between polls (官方建议 ≥5s)
_DEFAULT_POLL_TIMEOUT = 120  # max total poll time
_MAX_RETRIES = 3
_RETRY_DELAY = 2.0  # seconds between retries
_OCR_VL_SEM_KEY = "semaphore:ocr_vl:v2"
_OCR_VL_SEM_MAX = 2  # max concurrent remote OCR calls across all processes

# SSRF and size limits for result URL download
_MAX_CONTENT_LENGTH_HEADER_BYTES = 50 * 1024 * 1024  # 50 MB (wire / Content-Length)
_MAX_DECODED_DOWNLOAD_BYTES = 100 * 1024 * 1024  # 100 MB after decoding
_MAX_JSONL_LINES = 50_000
_MAX_JSONL_LINE_LENGTH = (
    200_000  # 200 KB per line — any longer line rejects the download
)
_RESULT_DOWNLOAD_TIMEOUT = 60  # seconds


def _extract_from_entry(
    entry: dict,
    *,
    text_parts: list[str],
    confidences: list[float],
    layout_blocks: list[dict],
) -> None:
    """Extract text, confidence and layout blocks from a parsed JSONL entry.

    Shared by the streaming loop and final-line handler so extraction logic
    is identical regardless of where the entry was parsed.
    """
    result_data = entry.get("result")
    if not isinstance(result_data, dict):
        result_data = entry
    layout_results = (
        result_data.get("layoutParsingResults")
        if isinstance(result_data, dict)
        else None
    )
    if isinstance(layout_results, list):
        for lr in layout_results:
            if not isinstance(lr, dict):
                continue

            md = lr.get("markdown")
            md_text = md.get("text") if isinstance(md, dict) else None
            if md_text:
                text_parts.append(str(md_text))

            entry_conf = md.get("confidence") if isinstance(md, dict) else None
            if entry_conf is not None:
                try:
                    confidences.append(float(entry_conf))
                except (ValueError, TypeError):
                    pass

            block = _normalize_layout_block(lr)
            if block:
                layout_blocks.append(block)
        return

    # Fallback: top-level text/ocr_text/content fields
    entry_text = (
        entry.get("text") or entry.get("ocr_text") or entry.get("content") or ""
    )
    if entry_text:
        text_parts.append(str(entry_text))

    entry_conf = entry.get("confidence")
    if entry_conf is None:
        entry_conf = entry.get("score")
    if entry_conf is not None:
        try:
            confidences.append(float(entry_conf))
        except (ValueError, TypeError):
            pass


def _check_content_length(response: httpx.Response) -> None:
    """Raise ResultDownloadError if Content-Length exceeds the limit.

    No-op when the header is missing or unparseable.
    """
    cl = response.headers.get("Content-Length")
    if cl:
        try:
            if int(cl) > _MAX_CONTENT_LENGTH_HEADER_BYTES:
                raise ResultDownloadError(
                    f"Content-Length {cl} exceeds {_MAX_CONTENT_LENGTH_HEADER_BYTES}"
                )
        except (ValueError, TypeError):
            pass


def _validate_result_url_sync(url: str) -> str:
    """Validate a result download URL for safety.

    Checks: https scheme, no embedded credentials, every resolved IP globally routable.
    Raises ``ResultDownloadError`` for unsafe URLs.
    """
    parsed = urlparse(url)

    if parsed.scheme not in ("https",):
        raise ResultDownloadError(f"Result URL must use https, got {parsed.scheme!r}")

    hostname = parsed.hostname
    if not hostname:
        raise ResultDownloadError("Result URL has no hostname")
    if parsed.username is not None or parsed.password is not None:
        raise ResultDownloadError("Result URL must not embed credentials")

    try:
        addr_info = socket.getaddrinfo(hostname, parsed.port or 443)
        for _family, _type, _proto, _canonname, sockaddr in addr_info:
            ip = ipaddress.ip_address(str(sockaddr[0]).split("%", 1)[0])
            # is_global also rejects CGNAT, benchmarking, documentation,
            # multicast, unspecified and reserved ranges.
            if not ip.is_global or ip.is_multicast:
                raise ResultDownloadError(
                    f"Result URL resolves to a non-public address: {sockaddr[0]}"
                )
    except socket.gaierror as exc:
        raise ResultDownloadError(
            f"Result URL hostname resolution failed: {exc}"
        ) from exc

    return url


async def _validate_result_url(url: str) -> str:
    """Resolve and validate a result URL without blocking the event loop."""
    return await asyncio.to_thread(_validate_result_url_sync, url)


def _normalize_layout_block(lr: dict) -> dict | None:
    """Normalize a PaddleOCR-VL layoutParsingResult entry into a standard format.

    Handles multiple possible response structures and preserves all available
    metadata. Returns None if the block has no useful information.
    """
    if not isinstance(lr, dict):
        return None

    block: dict = {}

    # Extract text from various possible locations
    md = lr.get("markdown") if isinstance(lr.get("markdown"), dict) else None
    if md:
        block["text"] = md.get("text", "")
        block["markdown"] = md.get("text", "")
        conf = md.get("confidence")
        if conf is not None:
            try:
                block["confidence"] = float(conf)
            except (ValueError, TypeError):
                pass
    else:
        block["text"] = lr.get("text") or lr.get("content") or ""

    # Type/label/category from various possible keys.  Some API versions emit
    # a page-level Markdown block without a semantic label; promote it to a
    # table block when the markup itself is unambiguous.
    declared_type = lr.get("type") or lr.get("label") or lr.get("category") or "unknown"
    if str(declared_type).lower() in {"", "unknown", "text", "paragraph"}:
        table_text = str(block.get("markdown") or block.get("text") or "")
        if _contains_table_markup(table_text) or isinstance(lr.get("rows"), list):
            declared_type = "table"
    block["type"] = declared_type
    block["label"] = lr.get("label") or lr.get("type") or ""
    block["category"] = lr.get("category") or lr.get("type") or ""

    # Preserve provider-native table structures when available.  These fields
    # are bounded later by VisualRegion serialization before persistence.
    for key in ("html", "rows", "headers", "cells", "tokens", "ocr_tokens"):
        if key in lr:
            block[key] = lr[key]

    # Bbox from various possible keys
    bbox = lr.get("bbox") or lr.get("box") or lr.get("polygon") or lr.get("rect")
    if bbox and isinstance(bbox, (list, tuple)) and len(bbox) == 4:
        try:
            block["bbox"] = [float(v) for v in bbox]
        except (ValueError, TypeError):
            pass
    elif bbox and isinstance(bbox, (list, tuple)) and len(bbox) == 8:
        # Polygon format: [x0,y0,x1,y1,x2,y2,x3,y3] → bbox
        try:
            xs = [float(bbox[i]) for i in range(0, 8, 2)]
            ys = [float(bbox[i]) for i in range(1, 8, 2)]
            block["bbox"] = [min(xs), min(ys), max(xs), max(ys)]
            block["polygon"] = [float(v) for v in bbox]
        except (ValueError, TypeError):
            pass

    # Page number
    page = lr.get("page") or lr.get("page_num") or lr.get("pageNum")
    if page is not None:
        try:
            block["page"] = int(page)
        except (ValueError, TypeError):
            pass

    # Width/height from markdown or direct keys
    for dim in ("width", "height"):
        val = lr.get(dim) or (md and md.get(dim))
        if val is not None:
            try:
                block[dim] = float(val)
            except (ValueError, TypeError):
                pass

    # Preserve original raw block for debugging
    block["raw_block"] = lr

    # Skip blocks with no text and no bbox
    if not block.get("text") and not block.get("bbox"):
        return None

    return block


def _contains_table_markup(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    if "<table" in lowered and "</table>" in lowered:
        return True
    lines = text.splitlines()
    for index in range(len(lines) - 1):
        if "|" not in lines[index]:
            continue
        separator = lines[index + 1].strip().strip("|")
        parts = [part.strip() for part in separator.split("|")]
        if len(parts) >= 2 and all(
            part
            and set(part.replace(":", "").replace(" ", "")) <= {"-"}
            and part.count("-") >= 3
            for part in parts
        ):
            return True
    return False


class PaddleOCRVLClientError(Exception):
    """Base exception for PaddleOCR-VL client errors."""


class JobSubmissionError(PaddleOCRVLClientError):
    """Failed to submit an OCR job (transient — caller may retry).

    Carries ``status_code`` and ``retry_after`` from the HTTP response
    so retry logic can make informed decisions without regex parsing.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retry_after: float | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


class JobPollingError(PaddleOCRVLClientError):
    """Job polling failed or timed out."""


class ResultDownloadError(PaddleOCRVLClientError):
    """Failed to download or parse the OCR result."""


class ContractError(PaddleOCRVLClientError):
    """API response contract mismatch (non-transient — do NOT retry)."""


class CircuitBreakerOpenError(PaddleOCRVLClientError):
    """Circuit breaker is open — fast fail without attempting the operation."""


class _CircuitBreaker:
    """Simple circuit breaker for remote API calls.

    States: CLOSED → OPEN (on failures) → HALF_OPEN (after timeout) → CLOSED (on success)

    Threshold and recovery timeout are shared across submit, poll, and download.
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        name: str = "default",
    ):
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._name = name
        self._state = self.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0

    @property
    def state(self) -> str:
        return self._state

    def record_success(self) -> None:
        self._failure_count = 0
        if self._state == self.HALF_OPEN:
            logger.info("Circuit breaker %s: half_open → closed (success)", self._name)
        self._state = self.CLOSED

    def record_failure(self) -> None:
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._failure_count >= self._failure_threshold:
            logger.warning(
                "Circuit breaker %s: opened after %d failures",
                self._name,
                self._failure_count,
            )
            self._state = self.OPEN

    def check(self) -> None:
        """Raise CircuitBreakerOpenError if the breaker is open and not ready to half-open."""
        if self._state == self.CLOSED:
            return
        if self._state == self.OPEN:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self._recovery_timeout:
                logger.info(
                    "Circuit breaker %s: open → half_open (recovery)", self._name
                )
                self._state = self.HALF_OPEN
                return
            raise CircuitBreakerOpenError(
                f"Circuit breaker {self._name} is open "
                f"(failures={self._failure_count}, recovery_in={self._recovery_timeout - elapsed:.0f}s)"
            )
        # HALF_OPEN: allow probe
        return


class PaddleOCRVLResult:
    """Parsed OCR result from PaddleOCR-VL.

    In addition to concatenated text and confidence, preserves the structured
    layout blocks from PaddleOCR-VL's layoutParsingResults. Each block may
    contain bbox, type, text/markdown, and other metadata.
    """

    def __init__(
        self,
        text: str,
        confidence: float = 0.0,
        raw: dict | None = None,
        layout_blocks: list[dict] | None = None,
        raw_entries: list[dict] | None = None,
    ):
        self.text = text
        self.confidence = confidence
        self.raw = raw or {}
        self.layout_blocks = layout_blocks or []
        self.raw_entries = raw_entries or []

    def get_blocks_by_type(self, block_type: str) -> list[dict]:
        """Return layout blocks matching a given type."""
        return [
            b
            for b in self.layout_blocks
            if b.get("type") == block_type or b.get("label") == block_type
        ]

    def get_blocks_by_category(self, category: str) -> list[dict]:
        """Return layout blocks matching a given category."""
        return [b for b in self.layout_blocks if b.get("category") == category]


class PaddleOCRVLClient:
    """Async HTTP client for PaddleOCR-VL API.

    Uses a single shared ``httpx.AsyncClient`` for connection pooling
    across all submit/poll/download requests.
    """

    def __init__(
        self,
        api_token: str,
        base_url: str = _DEFAULT_BASE_URL,
        model: str = "PaddleOCR-VL-1.6",
        poll_interval: float = _DEFAULT_POLL_INTERVAL,
        poll_timeout: float = _DEFAULT_POLL_TIMEOUT,
        max_retries: int = _MAX_RETRIES,
    ):
        self._api_token = api_token
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._poll_interval = poll_interval
        self._poll_timeout = poll_timeout
        self._max_retries = max_retries

        # Shared HTTP client with connection pooling
        self._client: httpx.AsyncClient | None = None
        # Result downloads follow provider-supplied URLs, so they use a client that
        # only connects to public IPs (DNS is resolved and checked at connect time).
        self._download_client: httpx.AsyncClient | None = None

        # Circuit breaker
        self._circuit_breaker = _CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=30.0,
            name="paddleocr-vl",
        )

    async def close(self) -> None:
        """Close the shared HTTP client and release connections."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        if self._download_client is not None:
            await self._download_client.aclose()
            self._download_client = None

    @staticmethod
    def _restricted() -> bool:
        """Return True when the distributed OCR limit must fail closed."""
        from app.core.config import settings

        if str(settings.APP_ENV).strip().lower() == "production":
            return True
        try:
            return detect_deployment_profile() == DeploymentProfile.CLOUD_API
        except Exception:
            return True

    async def _acquire_semaphore(self) -> str | bool | None:
        """Acquire one expiring cross-process lease for an OCR operation.

        Returns the unique Redis lease token when acquired, ``False`` when
        capacity is full, and ``None`` for the single-request local mode where
        no global limit exists.  A sorted-set lease is used instead of a shared
        counter so a crashed request expires independently and cannot leak
        capacity under sustained traffic.

        In production/cloud_api a Redis failure is fail-closed: it raises
        instead of silently dropping the global concurrency limit, which would
        otherwise let a Redis outage overload the external OCR service.
        """
        if not _OCR_VL_SEM_KEY:
            return None
        token = uuid.uuid4().hex
        ttl = int(max(600, self._poll_timeout + _RESULT_DOWNLOAD_TIMEOUT + 180))
        try:
            from app.core.cache import cache

            client = await cache._ensure_client()
            if client is None:
                if self._restricted():
                    raise RuntimeError("Redis client unavailable")
                return None
            acquired = await client.eval(
                """
                local now_parts = redis.call('TIME')
                local now = tonumber(now_parts[1]) + tonumber(now_parts[2]) / 1000000
                redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now)
                if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[2]) then
                    return 0
                end
                redis.call('ZADD', KEYS[1], now + tonumber(ARGV[3]), ARGV[1])
                redis.call('EXPIRE', KEYS[1], math.ceil(tonumber(ARGV[3])) + 60)
                return 1
                """,
                1,
                _OCR_VL_SEM_KEY,
                token,
                _OCR_VL_SEM_MAX,
                ttl,
            )
            return token if int(acquired) == 1 else False
        except Exception as exc:
            if self._restricted():
                logger.error(
                    "[PaddleOCR-VL] distributed semaphore unavailable in "
                    "restricted environment; refusing OCR to protect the "
                    "external service: %s",
                    exc,
                )
                raise JobSubmissionError(
                    "PaddleOCR-VL distributed concurrency unavailable"
                ) from exc
            logger.warning(
                "[PaddleOCR-VL] distributed semaphore unavailable; "
                "continuing without global limit: %s",
                exc,
            )
            return None

    async def _release_semaphore(self, token: str) -> None:
        """Release only the exact Redis lease held by this operation."""
        if not _OCR_VL_SEM_KEY or not token:
            return
        try:
            from app.core.cache import cache

            client = await cache._ensure_client()
            if client is None:
                return
            await client.eval(
                """
                local removed = redis.call('ZREM', KEYS[1], ARGV[1])
                if redis.call('ZCARD', KEYS[1]) == 0 then
                    redis.call('DEL', KEYS[1])
                end
                return removed
                """,
                1,
                _OCR_VL_SEM_KEY,
                token,
            )
        except Exception as exc:
            logger.warning(
                "[PaddleOCR-VL] failed to release distributed semaphore lease: %s",
                exc,
            )

    @staticmethod
    def _jitter_delay(base: float, attempt: int, max_delay: float = 30.0) -> float:
        """Exponential backoff with jitter: base * 2^attempt + random(0, 1)."""
        delay = min(base * (2**attempt) + random.random(), max_delay)
        return delay

    def _get_client(self) -> httpx.AsyncClient:
        """Lazy-initialize and return the shared HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                limits=httpx.Limits(
                    max_connections=10,
                    max_keepalive_connections=5,
                ),
                timeout=httpx.Timeout(60.0, connect=10.0),
            )
        return self._client

    def _get_download_client(self) -> httpx.AsyncClient:
        if self._download_client is None:
            from app.services.safe_httpx import build_public_only_client

            self._download_client = build_public_only_client(
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
                timeout=httpx.Timeout(60.0, connect=10.0),
            )
        return self._download_client

    @property
    def is_available(self) -> bool:
        return bool(self._api_token)

    @classmethod
    async def from_resolver(
        cls,
        resolver: Any,
        *,
        fallback_token: str = "",
        fallback_base_url: str = "",
    ) -> PaddleOCRVLClient:
        """Create a client from an ``AIModelConfigResolver`` (admin_ai_settings).

        Resolves ``AICapability.OCR_VL`` from the database and returns a
        fully configured client. Falls back to explicit parameters when the
        resolver has no config (graceful degradation).

        Usage::

            from app.services.model_config_resolver import (
                AIModelConfigResolver, AICapability,
            )
            resolver = AIModelConfigResolver(db)
            client = await PaddleOCRVLClient.from_resolver(resolver)
        """
        try:
            from app.services.model_config_resolver import (
                AICapability,
            )

            resolved = await resolver.resolve_for_capability(AICapability.OCR_VL)
            api_token = await resolver.resolve_secret(resolved)
            base_url = resolved.endpoint or fallback_base_url or _DEFAULT_BASE_URL
            model = resolved.model_name or "PaddleOCR-VL-1.6"
            poll_timeout = getattr(resolved, "timeout_seconds", _DEFAULT_POLL_TIMEOUT)
            max_retries = getattr(resolved, "max_retries", _MAX_RETRIES)
        except (ImportError, ValueError, Exception) as exc:
            logger.debug("from_resolver fallback: %s", exc)
            api_token = fallback_token
            base_url = fallback_base_url or _DEFAULT_BASE_URL
            model = "PaddleOCR-VL-1.6"
            poll_timeout = _DEFAULT_POLL_TIMEOUT
            max_retries = _MAX_RETRIES

        return cls(
            api_token=api_token,
            base_url=base_url,
            model=model,
            poll_timeout=poll_timeout,
            max_retries=max_retries,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def ocr_image(
        self,
        image_bytes: bytes,
        filename: str = "image.png",
    ) -> PaddleOCRVLResult:
        """Submit one image while holding one distributed slot."""
        self._circuit_breaker.check()
        redis_slot_held = await self._acquire_semaphore()
        if redis_slot_held is False:
            raise JobSubmissionError("PaddleOCR-VL concurrency is at capacity")
        job_id: str | None = None
        try:
            job_id = await self._submit_with_retry(image_bytes, filename)
            result_data = await self._poll_with_timeout(job_id)
            result = await self._parse_result(result_data)
            self._circuit_breaker.record_success()
            return result
        except asyncio.CancelledError:
            logger.info("[PaddleOCR-VL] ocr_image cancelled")
            if job_id:
                await self.cancel_job(job_id)
            raise
        except Exception:
            self._circuit_breaker.record_failure()
            if job_id:
                await self.cancel_job(job_id)
            raise
        finally:
            if isinstance(redis_slot_held, str):
                await self._release_semaphore(redis_slot_held)

    async def batch_ocr(
        self,
        images: list[tuple[bytes, str]],
        *,
        max_concurrency: int = 2,
        progress_callback: callable | None = None,
    ) -> list[PaddleOCRVLResult | None]:
        """OCR a batch without creating one retained task per image."""
        if not images:
            return []
        worker_count = max(1, min(int(max_concurrency), len(images)))
        results: list[PaddleOCRVLResult | None] = [None] * len(images)
        next_index = 0
        completed = 0

        async def _worker() -> None:
            nonlocal next_index, completed
            while True:
                idx = next_index
                next_index += 1
                if idx >= len(images):
                    return
                data, name = images[idx]
                try:
                    results[idx] = await self.ocr_image(data, name)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning(
                        "[PaddleOCR-VL] batch image %d/%d failed: %s",
                        idx + 1,
                        len(images),
                        exc,
                    )
                finally:
                    completed += 1
                    if progress_callback:
                        progress_callback(completed, len(images))

        tasks = [
            asyncio.create_task(_worker(), name=f"ocr-vl-batch-{i}")
            for i in range(worker_count)
        ]
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        return results

    async def ocr_image_url(
        self,
        file_url: str,
    ) -> PaddleOCRVLResult:
        """Submit one URL while holding one distributed slot."""
        self._circuit_breaker.check()
        redis_slot_held = await self._acquire_semaphore()
        if redis_slot_held is False:
            raise JobSubmissionError("PaddleOCR-VL concurrency is at capacity")
        job_id: str | None = None
        try:
            job_id = await self._submit_url_with_retry(file_url)
            result_data = await self._poll_with_timeout(job_id)
            result = await self._parse_result(result_data)
            self._circuit_breaker.record_success()
            return result
        except asyncio.CancelledError:
            logger.info("[PaddleOCR-VL] ocr_image_url cancelled")
            if job_id:
                await self.cancel_job(job_id)
            raise
        except Exception:
            self._circuit_breaker.record_failure()
            if job_id:
                await self.cancel_job(job_id)
            raise
        finally:
            if isinstance(redis_slot_held, str):
                await self._release_semaphore(redis_slot_held)

    # ------------------------------------------------------------------
    # Job submission
    # ------------------------------------------------------------------

    async def _submit_job(self, image_bytes: bytes, filename: str) -> str:
        """Submit an OCR job via multipart upload. Returns job_id."""
        url = urljoin(self._base_url, _OCR_VL_API_PATH)
        logger.info("PaddleOCR-VL submit_job url=%s", url)
        headers = {
            **get_trace_headers(),
            "Authorization": f"Bearer {self._api_token}",
        }

        client = self._get_client()
        response = await client.post(
            url,
            headers=headers,
            files={"file": (filename, image_bytes, "image/png")},
            data={"model": self._model},
        )
        _raise_on_bad_status(response)
        body = _parse_json_body(response)
        job_id = _extract_job_id(_unwrap_data(body))
        logger.info("[PaddleOCR-VL] submit response job_id=%s", job_id)
        return job_id

    async def _submit_url_job(self, file_url: str) -> str:
        """Submit an OCR job via URL. Returns job_id."""
        url = urljoin(self._base_url, _OCR_VL_API_PATH)
        logger.info("PaddleOCR-VL submit_url_job url=%s file_url=%.120s", url, file_url)
        headers = {
            **get_trace_headers(),
            "Authorization": f"Bearer {self._api_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "fileUrl": file_url,
            "model": self._model,
        }

        client = self._get_client()
        response = await client.post(url, headers=headers, json=payload)
        _raise_on_bad_status(response)
        body = _parse_json_body(response)
        data = _unwrap_data(body)
        job_id = _extract_job_id(data)
        logger.info("[PaddleOCR-VL] submit_url response job_id=%s", job_id)
        return job_id

    async def _submit_with_retry(self, image_bytes: bytes, filename: str) -> str:
        """Submit job with retry. Returns job_id or raises."""
        return await self._retry_submit(
            lambda: self._submit_job(image_bytes, filename),
            "file submit",
        )

    async def _submit_url_with_retry(self, file_url: str) -> str:
        """Submit URL job with retry."""
        return await self._retry_submit(
            lambda: self._submit_url_job(file_url),
            "URL submit",
        )

    async def _retry_submit(self, submit_fn, desc: str) -> str:
        """Generic retry wrapper for job submission.

        Retry policy:
        - Network/timeout errors → retry with exponential backoff
        - 408 Request Timeout / 5xx → retry
        - 429 Too Many Requests → retry with Retry-After if available
        - 4xx (except 408/429) → fail immediately (non-retriable)
        - ContractError → fail immediately (non-retriable)
        """
        last_error: Exception | None = None

        for attempt in range(self._max_retries):
            try:
                return await submit_fn()
            except ContractError:
                raise
            except JobSubmissionError as exc:
                last_error = exc

                # Non-retriable client errors (except 408/429)
                if exc.status_code is not None:
                    sc = exc.status_code
                    if 400 <= sc < 500 and sc not in (408, 429):
                        raise

                logger.warning(
                    "PaddleOCR-VL %s attempt %d/%d failed: %s",
                    desc,
                    attempt + 1,
                    self._max_retries,
                    exc,
                )

                if attempt < self._max_retries - 1:
                    retry_delay = self._jitter_delay(_RETRY_DELAY, attempt)
                    # 429 with Retry-After from actual response header
                    if exc.retry_after is not None:
                        retry_delay = min(exc.retry_after, 30.0)
                    await asyncio.sleep(retry_delay)

            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                logger.warning(
                    "PaddleOCR-VL %s attempt %d/%d network error: %s",
                    desc,
                    attempt + 1,
                    self._max_retries,
                    exc,
                )
                if attempt < self._max_retries - 1:
                    await asyncio.sleep(self._jitter_delay(_RETRY_DELAY, attempt))

        logger.error(
            "PaddleOCR-VL %s exhausted retries=%d last_error=%s",
            desc,
            self._max_retries,
            last_error,
        )
        raise JobSubmissionError(
            f"All {self._max_retries} {desc} attempts failed: {last_error}"
        ) from last_error

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    async def _poll_job_status(self, job_id: str) -> dict:
        """Poll the job status once. Returns the unwrapped data dict."""
        url = urljoin(self._base_url, f"{_OCR_VL_API_PATH}/{job_id}")
        logger.debug("PaddleOCR-VL poll_job url=%s job_id=%s", url, job_id)
        headers = {
            **get_trace_headers(),
            "Authorization": f"Bearer {self._api_token}",
        }

        client = self._get_client()
        response = await client.get(url, headers=headers)
        if response.status_code != 200:
            raise JobPollingError(
                f"Poll HTTP {response.status_code}: {response.text[:200]}"
            )
        body = _parse_json_body(response)
        # Poll responses also use the same envelope: {code, msg, data}
        code = body.get("code", -1)
        if code != 0:
            msg = body.get("msg") or body.get("message") or "unknown"
            raise JobPollingError(f"Job {job_id} poll API error: code={code} msg={msg}")
        data = body.get("data")
        if not isinstance(data, dict):
            raise JobPollingError(f"Job {job_id} poll response missing 'data'")
        logger.info(
            "[PaddleOCR-VL] poll job=%s state=%s",
            job_id,
            data.get("state", "unknown"),
        )
        return data

    async def _poll_with_timeout(self, job_id: str) -> dict:
        """Poll until done/failed or timeout. Returns the result data dict."""
        deadline = time.monotonic() + self._poll_timeout
        last_status: str | None = None

        # 首次轮询前等待 5s，避免 API 还没开始处理就狂刷
        initial_wait = min(5.0, self._poll_timeout * 0.1)
        await asyncio.sleep(initial_wait)

        while True:
            remaining = deadline - time.monotonic()

            if remaining <= 0:
                raise JobPollingError(
                    f"Job {job_id} polling timed out after {self._poll_timeout}s "
                    f"(last status: {last_status})"
                )

            try:
                body = await self._poll_job_status(job_id)
            except (
                JobPollingError,
                httpx.TimeoutException,
                httpx.TransportError,
            ) as exc:
                logger.warning("Poll job %s failed, retrying: %s", job_id, exc)
                self._circuit_breaker.record_failure()
                # Cap sleep to remaining deadline
                sleep_time = min(self._poll_interval, max(remaining * 0.1, 1.0))
                await asyncio.sleep(sleep_time)
                continue

            self._circuit_breaker.record_success()

            status = (body.get("status") or body.get("state") or "").lower()
            last_status = status

            if status in ("done", "completed", "success", "finished"):
                return body
            if status in ("failed", "error"):
                error_msg = (
                    body.get("errorMsg")
                    or body.get("error")
                    or body.get("message")
                    or "unknown error"
                )
                raise JobPollingError(f"Job {job_id} failed: {error_msg}")

            # still pending/running — wait, capped to remaining deadline
            sleep_time = min(self._poll_interval, max(remaining * 0.5, 0.5))
            await asyncio.sleep(sleep_time)

    # ------------------------------------------------------------------
    # Cancel remote job
    # ------------------------------------------------------------------

    async def cancel_job(self, job_id: str) -> None:
        """Attempt to cancel a running remote OCR job (best-effort)."""
        try:
            url = urljoin(self._base_url, f"{_OCR_VL_API_PATH}/{job_id}")
            headers = {
                **get_trace_headers(),
                "Authorization": f"Bearer {self._api_token}",
            }
            client = self._get_client()
            await client.delete(url, headers=headers)
            logger.info("[PaddleOCR-VL] cancel job=%s", job_id)
        except Exception as exc:
            logger.warning("[PaddleOCR-VL] cancel job=%s failed: %s", job_id, exc)

    # ------------------------------------------------------------------
    # Result parsing
    # ------------------------------------------------------------------

    async def _download_and_parse_jsonl(
        self, url: str
    ) -> tuple[str, float, list[dict], list[dict]]:
        """Download JSONL from url and extract text, confidence, layout blocks, and raw entries.

        Uses bounded streaming to enforce size/line limits mid-read — never buffers
        the full response. SSRF validation is applied to the initial URL and each
        redirect hop before connecting.
        """
        url = await _validate_result_url(url)

        client = self._get_download_client()

        # Disable auto-redirect: validate each hop manually before connecting
        async with client.stream("GET", url, follow_redirects=False) as response:
            # Content-Length pre-check
            _check_content_length(response)

            if response.status_code in (301, 302, 303, 307, 308):
                location = str(response.headers.get("location", ""))
                if not location:
                    raise ResultDownloadError("Redirect with no Location header")
                # Resolve relative redirects, then validate DNS off the event loop.
                redirect_url = urljoin(str(response.url), location)
                redirect_url = await _validate_result_url(redirect_url)
                async with client.stream(
                    "GET", redirect_url, follow_redirects=False
                ) as final_resp:
                    final_resp.raise_for_status()
                    # Content-Length pre-check on final response too
                    _check_content_length(final_resp)
                    (
                        raw_text,
                        confidence,
                        layout_blocks,
                        raw_entries,
                    ) = await self._stream_and_parse(final_resp)
            else:
                response.raise_for_status()
                (
                    raw_text,
                    confidence,
                    layout_blocks,
                    raw_entries,
                ) = await self._stream_and_parse(response)

        return raw_text, confidence, layout_blocks, raw_entries

    async def _stream_and_parse(
        self,
        response: httpx.Response,
    ) -> tuple[str, float, list[dict], list[dict]]:
        """Bounded streaming parse of JSONL response.

        Processes chunks as they arrive: split on newlines, parse complete JSONL
        lines immediately, enforce size and line-count limits mid-stream.

        This implementation is *bounded streaming* — it never buffers the full
        response, but raw_entries and the final result are retained in memory.
        """
        total_downloaded = 0
        byte_buffer = bytearray()
        line_count = 0
        first_line = True

        text_parts: list[str] = []
        confidences: list[float] = []
        layout_blocks: list[dict] = []
        raw_entries: list[dict] = []

        async for chunk in response.aiter_bytes():
            chunk_len = len(chunk)
            total_downloaded += chunk_len

            if total_downloaded > _MAX_DECODED_DOWNLOAD_BYTES:
                raise ResultDownloadError(
                    f"Result download exceeded {_MAX_DECODED_DOWNLOAD_BYTES} decoded bytes"
                    f" at {total_downloaded} bytes"
                )

            byte_buffer.extend(chunk)

            # Process complete lines incrementally.  Avoid repeated immutable-byte
            # concatenation/splitting, which becomes quadratic for large results.
            while True:
                newline_pos = byte_buffer.find(b"\n")
                if newline_pos < 0:
                    break
                part = bytes(byte_buffer[:newline_pos])
                del byte_buffer[: newline_pos + 1]
                if not part and not first_line:
                    # Empty line (not the first, which could be BOM)
                    continue

                # Decode one complete line
                line_text = part.decode("utf-8", errors="replace")
                if first_line:
                    first_line = False
                    # Strip UTF-8 BOM if present
                    if line_text.startswith("﻿"):
                        line_text = line_text[1:]
                # Normalize CRLF: strip trailing \r
                if line_text.endswith("\r"):
                    line_text = line_text[:-1]
                # Enforce per-line length limit -- reject, do not skip
                if len(line_text) > _MAX_JSONL_LINE_LENGTH:
                    raise ResultDownloadError(
                        f"JSONL line {line_count + 1} length {len(line_text)} "
                        f"exceeds limit of {_MAX_JSONL_LINE_LENGTH}"
                    )

                stripped = line_text.strip()
                if not stripped:
                    continue

                line_count += 1
                if line_count > _MAX_JSONL_LINES:
                    raise ResultDownloadError(
                        f"Result JSONL has {line_count} lines, exceeds limit "
                        f"of {_MAX_JSONL_LINES}"
                    )

                # Parse JSONL line immediately
                try:
                    entry = json.loads(stripped)
                except json.JSONDecodeError:
                    continue

                raw_entries.append(entry)
                _extract_from_entry(
                    entry,
                    text_parts=text_parts,
                    confidences=confidences,
                    layout_blocks=layout_blocks,
                )

            # UTF-8 needs at most four bytes per code point.  Reject an
            # unterminated oversized line long before it can grow to the full
            # response limit.
            if len(byte_buffer) > _MAX_JSONL_LINE_LENGTH * 4:
                raise ResultDownloadError(
                    f"JSONL line byte length exceeds safe bound of "
                    f"{_MAX_JSONL_LINE_LENGTH * 4}"
                )

        # Handle final partial line (no trailing newline)
        if byte_buffer:
            line_text = bytes(byte_buffer).decode("utf-8", errors="replace")
            if first_line and line_text.startswith("﻿"):
                line_text = line_text[1:]
            if line_text.endswith("\r"):
                line_text = line_text[:-1]
            # Enforce per-line length limit -- reject, do not skip
            if len(line_text) > _MAX_JSONL_LINE_LENGTH:
                raise ResultDownloadError(
                    f"JSONL final line length {len(line_text)} "
                    f"exceeds limit of {_MAX_JSONL_LINE_LENGTH}"
                )

            stripped = line_text.strip()
            if stripped:
                line_count += 1
                if line_count > _MAX_JSONL_LINES:
                    raise ResultDownloadError(
                        f"Result JSONL has {line_count} lines, exceeds limit "
                        f"of {_MAX_JSONL_LINES}"
                    )
                try:
                    entry = json.loads(stripped)
                except json.JSONDecodeError:
                    pass
                else:
                    raw_entries.append(entry)
                    _extract_from_entry(
                        entry,
                        text_parts=text_parts,
                        confidences=confidences,
                        layout_blocks=layout_blocks,
                    )

        if not raw_entries:
            return "", 0.0, [], []

        full_text = "\n".join(text_parts)
        avg_confidence = (
            round(sum(confidences) / len(confidences), 4) if confidences else 0.0
        )
        return full_text, avg_confidence, layout_blocks, raw_entries

    async def _parse_result(self, job_data: dict) -> PaddleOCRVLResult:
        """Download and parse the OCR result from resultUrl.jsonUrl."""
        json_url = _extract_result_url(job_data)

        (
            raw_text,
            confidence,
            layout_blocks,
            raw_entries,
        ) = await self._download_and_parse_jsonl(json_url)
        return PaddleOCRVLResult(
            text=raw_text,
            confidence=confidence,
            raw={"job_data": job_data, "result_url": json_url},
            layout_blocks=layout_blocks,
            raw_entries=raw_entries,
        )
