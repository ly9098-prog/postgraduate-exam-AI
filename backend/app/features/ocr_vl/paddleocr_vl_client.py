"""PaddleOCR-VL API client — async HTTP client for the external OCR service.

API flow:
    1. POST /api/v2/ocr/jobs  (submit image → receive job_id)
    2. GET  /api/v2/ocr/jobs/{job_id}  (poll until done/failed)
    3. Download result from resultUrl.jsonUrl  (JSONL → structured text)
"""

from __future__ import annotations

import asyncio
import codecs
import ipaddress
import json
import logging
import socket
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from urllib.parse import urljoin

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
        f"No result URL in job data: "
        f"{json.dumps(job_data, ensure_ascii=False)[:300]}"
    )


_DEFAULT_BASE_URL = "https://paddleocr.aistudio-app.com"
_OCR_VL_API_PATH = "/api/v2/ocr/jobs"   # endpoint path used by urljoin
_DEFAULT_POLL_INTERVAL = 5.0  # seconds between polls (官方建议 ≥5s)
_DEFAULT_POLL_TIMEOUT = 120  # max total poll time
_MAX_RETRIES = 3
_RETRY_DELAY = 2.0  # seconds between retries

# SSRF and size limits for result URL download
_MAX_CONTENT_LENGTH_HEADER_BYTES = 50 * 1024 * 1024  # 50 MB (wire / Content-Length)
_MAX_DECODED_DOWNLOAD_BYTES = 100 * 1024 * 1024     # 100 MB after decoding
_MAX_JSONL_LINES = 50_000
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
    result_data = entry.get("result") or entry
    layout_results = result_data.get("layoutParsingResults") if isinstance(result_data, dict) else None
    if isinstance(layout_results, list):
        for lr in layout_results:
            if not isinstance(lr, dict):
                continue

            md = lr.get("markdown") if isinstance(lr, dict) else None
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
        entry.get("text")
        or entry.get("ocr_text")
        or entry.get("content")
        or ""
    )
    if entry_text:
        text_parts.append(str(entry_text))

    entry_conf = entry.get("confidence") or entry.get("score")
    if entry_conf is not None:
        try:
            confidences.append(float(entry_conf))
        except (ValueError, TypeError):
            pass


def _validate_result_url(url: str) -> str:
    """Validate a result download URL for safety.

    Checks: https scheme, non-private resolved IP, no loopback/link-local.
    Raises ``ResultDownloadError`` for unsafe URLs.
    """
    parsed = urlparse(url)

    if parsed.scheme not in ("https",):
        raise ResultDownloadError(
            f"Result URL must use https, got {parsed.scheme!r}"
        )

    hostname = parsed.hostname
    if not hostname:
        raise ResultDownloadError("Result URL has no hostname")

    try:
        addr_info = socket.getaddrinfo(hostname, parsed.port or 443)
        for _family, _type, _proto, _canonname, sockaddr in addr_info:
            ip = ipaddress.ip_address(sockaddr[0])
            if ip.is_private or ip.is_loopback or ip.is_link_local:
                raise ResultDownloadError(
                    f"Result URL resolves to private/loopback/link-local "
                    f"address: {sockaddr[0]}"
                )
    except socket.gaierror as exc:
        raise ResultDownloadError(
            f"Result URL hostname resolution failed: {exc}"
        ) from exc

    return url


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

    # Type/label/category from various possible keys
    block["type"] = lr.get("type") or lr.get("label") or lr.get("category") or "unknown"
    block["label"] = lr.get("label") or lr.get("type") or ""
    block["category"] = lr.get("category") or lr.get("type") or ""

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
                self._name, self._failure_count,
            )
            self._state = self.OPEN

    def check(self) -> None:
        """Raise CircuitBreakerOpenError if the breaker is open and not ready to half-open."""
        if self._state == self.CLOSED:
            return
        if self._state == self.OPEN:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self._recovery_timeout:
                logger.info("Circuit breaker %s: open → half_open (recovery)", self._name)
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
        return [b for b in self.layout_blocks if b.get("type") == block_type or b.get("label") == block_type]

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
                AIModelConfigResolver,
            )
            resolved = await resolver.resolve_for_capability(
                AICapability.OCR_VL
            )
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
        """Submit a single image for OCR and return the result."""
        self._circuit_breaker.check()
        try:
            job_id = await self._submit_with_retry(image_bytes, filename)
            self._circuit_breaker.record_success()
            result_data = await self._poll_with_timeout(job_id)
            return await self._parse_result(result_data)
        except asyncio.CancelledError:
            logger.info("[PaddleOCR-VL] ocr_image cancelled")
            raise

    async def ocr_image_url(
        self,
        file_url: str,
    ) -> PaddleOCRVLResult:
        """Submit an image URL for OCR and return the result."""
        self._circuit_breaker.check()
        try:
            job_id = await self._submit_url_with_retry(file_url)
            self._circuit_breaker.record_success()
            result_data = await self._poll_with_timeout(job_id)
            return await self._parse_result(result_data)
        except asyncio.CancelledError:
            logger.info("[PaddleOCR-VL] ocr_image_url cancelled")
            raise

    # ------------------------------------------------------------------
    # Job submission
    # ------------------------------------------------------------------

    async def _submit_job(self, image_bytes: bytes, filename: str) -> str:
        """Submit an OCR job via multipart upload. Returns job_id."""
        url = urljoin(self._base_url, _OCR_VL_API_PATH)
        logger.info("PaddleOCR-VL submit_job url=%s", url)
        headers = {"Authorization": f"Bearer {self._api_token}"}

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
                    desc, attempt + 1, self._max_retries, exc,
                )

                if attempt < self._max_retries - 1:
                    retry_delay = _RETRY_DELAY * (attempt + 1)
                    # 429 with Retry-After from actual response header
                    if exc.retry_after is not None:
                        retry_delay = min(exc.retry_after, 30.0)
                    await asyncio.sleep(retry_delay)

            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                logger.warning(
                    "PaddleOCR-VL %s attempt %d/%d network error: %s",
                    desc, attempt + 1, self._max_retries, exc,
                )
                if attempt < self._max_retries - 1:
                    await asyncio.sleep(_RETRY_DELAY * (attempt + 1))

        logger.error(
            "PaddleOCR-VL %s exhausted retries=%d last_error=%s",
            desc, self._max_retries, last_error,
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
        headers = {"Authorization": f"Bearer {self._api_token}"}

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
            raise JobPollingError(
                f"Job {job_id} poll API error: code={code} msg={msg}"
            )
        data = body.get("data")
        if not isinstance(data, dict):
            raise JobPollingError(
                f"Job {job_id} poll response missing 'data'"
            )
        logger.info(
            "[PaddleOCR-VL] poll job=%s state=%s",
            job_id, data.get("state", "unknown"),
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
            except (JobPollingError, httpx.TimeoutException, httpx.TransportError) as exc:
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
                error_msg = body.get("errorMsg") or body.get("error") or body.get("message") or "unknown error"
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
            headers = {"Authorization": f"Bearer {self._api_token}"}
            client = self._get_client()
            await client.delete(url, headers=headers)
            logger.info("[PaddleOCR-VL] cancel job=%s", job_id)
        except Exception as exc:
            logger.warning("[PaddleOCR-VL] cancel job=%s failed: %s", job_id, exc)

    # ------------------------------------------------------------------
    # Result parsing
    # ------------------------------------------------------------------

    async def _download_and_parse_jsonl(self, url: str) -> tuple[str, float, list[dict], list[dict]]:
        """Download JSONL from url and extract text, confidence, layout blocks, and raw entries.

        Uses bounded streaming to enforce size/line limits mid-read — never buffers
        the full response. SSRF validation is applied to the initial URL and each
        redirect hop before connecting.
        """
        url = _validate_result_url(url)

        client = self._get_client()

        # Disable auto-redirect: validate each hop manually before connecting
        async with client.stream("GET", url, follow_redirects=False) as response:
            # Content-Length pre-check
            cl = response.headers.get("Content-Length")
            if cl:
                try:
                    if int(cl) > _MAX_CONTENT_LENGTH_HEADER_BYTES:
                        raise ResultDownloadError(
                            f"Content-Length {cl} exceeds {_MAX_CONTENT_LENGTH_HEADER_BYTES}"
                        )
                except (ValueError, TypeError):
                    pass

            if response.status_code in (301, 302, 303, 307, 308):
                redirect_url = str(response.headers.get("location", ""))
                if not redirect_url:
                    raise ResultDownloadError("Redirect with no Location header")
                # Validate redirect target before connecting
                _validate_result_url(redirect_url)
                async with client.stream("GET", redirect_url, follow_redirects=False) as final_resp:
                    final_resp.raise_for_status()
                    raw_text, confidence, layout_blocks, raw_entries = await self._stream_and_parse(final_resp)
            else:
                response.raise_for_status()
                raw_text, confidence, layout_blocks, raw_entries = await self._stream_and_parse(response)

        return raw_text, confidence, layout_blocks, raw_entries

    async def _stream_and_parse(
        self, response: httpx.Response,
    ) -> tuple[str, float, list[dict], list[dict]]:
        """Bounded streaming parse of JSONL response.

        Processes chunks as they arrive: split on newlines, parse complete JSONL
        lines immediately, enforce size and line-count limits mid-stream.

        This implementation is *bounded streaming* — it never buffers the full
        response, but raw_entries and the final result are retained in memory.
        """
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        total_compressed = 0
        byte_buffer = b""
        line_count = 0
        first_line = True

        text_parts: list[str] = []
        confidences: list[float] = []
        layout_blocks: list[dict] = []
        raw_entries: list[dict] = []

        async for chunk in response.aiter_bytes():
            chunk_len = len(chunk)
            total_compressed += chunk_len

            if total_compressed > _MAX_CONTENT_LENGTH_HEADER_BYTES:
                raise ResultDownloadError(
                    f"Result download exceeded {_MAX_CONTENT_LENGTH_HEADER_BYTES} bytes"
                    f" (compressed) at {total_compressed} bytes"
                )

            byte_buffer += chunk

            # Guard: a single line without newline must not consume unlimited memory
            if b"\n" not in byte_buffer:
                raw_so_far = len(byte_buffer)
                decoded_estimate = raw_so_far  # upper bound (ASCII) or less (multi-byte)
                if decoded_estimate > _MAX_DECODED_DOWNLOAD_BYTES:
                    raise ResultDownloadError(
                        f"Result line exceeds {_MAX_DECODED_DOWNLOAD_BYTES} decoded bytes"
                        f" without newline"
                    )
                continue

            # Split on newlines and process complete lines
            parts = byte_buffer.split(b"\n")
            # Everything except the last element — the last may be incomplete
            complete_parts = parts[:-1]
            byte_buffer = parts[-1]

            for part in complete_parts:
                if not part and not first_line:
                    # Empty line (not the first, which could be BOM)
                    continue

                # Decode one complete line
                line_text = decoder.decode(part)
                if first_line:
                    first_line = False
                    # Strip UTF-8 BOM if present
                    if line_text.startswith("﻿"):
                        line_text = line_text[1:]
                # Normalize CRLF: strip trailing \r
                if line_text.endswith("\r"):
                    line_text = line_text[:-1]

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

        # Handle final partial line (no trailing newline)
        if byte_buffer:
            line_text = decoder.decode(byte_buffer, final=True)
            if first_line and line_text.startswith("﻿"):
                line_text = line_text[1:]
            if line_text.endswith("\r"):
                line_text = line_text[:-1]

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

        raw_text, confidence, layout_blocks, raw_entries = await self._download_and_parse_jsonl(json_url)
        return PaddleOCRVLResult(
            text=raw_text,
            confidence=confidence,
            raw={"job_data": job_data, "result_url": json_url},
            layout_blocks=layout_blocks,
            raw_entries=raw_entries,
        )
