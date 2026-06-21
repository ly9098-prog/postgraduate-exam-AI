"""PaddleOCR-VL API client — async HTTP client for the external OCR service.

API flow:
    1. POST /api/v2/ocr/jobs  (submit image → receive job_id)
    2. GET  /api/v2/ocr/jobs/{job_id}  (poll until done/failed)
    3. Download result from resultUrl.jsonUrl  (JSONL → structured text)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------


def _raise_on_bad_status(response: httpx.Response) -> None:
    """Raise JobSubmissionError if response status is not 200."""
    if response.status_code != 200:
        raise JobSubmissionError(
            f"HTTP {response.status_code}: {response.text[:200]}"
        )


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
    """Extract the result JSON URL from a job response dict.

    Tries multiple field locations in priority order:
      result.jsonUrl → result.url → resultUrl → resultUrl.jsonUrl
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
        f"No result URL in job response: "
        f"{json.dumps(job_data, ensure_ascii=False)[:300]}"
    )

# Defaults
_DEFAULT_BASE_URL = "https://paddleocr.aistudio-app.com"
_DEFAULT_POLL_INTERVAL = 1.5  # seconds between polls
_DEFAULT_POLL_TIMEOUT = 120  # max total poll time
_MAX_RETRIES = 3
_RETRY_DELAY = 2.0  # seconds between retries


class PaddleOCRVLClientError(Exception):
    """Base exception for PaddleOCR-VL client errors."""


class JobSubmissionError(PaddleOCRVLClientError):
    """Failed to submit an OCR job."""


class JobPollingError(PaddleOCRVLClientError):
    """Job polling failed or timed out."""


class ResultDownloadError(PaddleOCRVLClientError):
    """Failed to download or parse the OCR result."""


class PaddleOCRVLResult:
    """Parsed OCR result from PaddleOCR-VL."""

    def __init__(
        self,
        text: str,
        confidence: float = 0.0,
        raw: dict | None = None,
    ):
        self.text = text
        self.confidence = confidence
        self.raw = raw or {}


class PaddleOCRVLClient:
    """Async HTTP client for PaddleOCR-VL API."""

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

    @property
    def is_available(self) -> bool:
        return bool(self._api_token)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def ocr_image(
        self,
        image_bytes: bytes,
        filename: str = "image.png",
    ) -> PaddleOCRVLResult:
        """Submit a single image for OCR and return the result."""
        job_id = await self._submit_with_retry(image_bytes, filename)
        result_data = await self._poll_with_timeout(job_id)
        return await self._parse_result(result_data)

    async def ocr_image_url(
        self,
        file_url: str,
    ) -> PaddleOCRVLResult:
        """Submit an image URL for OCR and return the result."""
        job_id = await self._submit_url_with_retry(file_url)
        result_data = await self._poll_with_timeout(job_id)
        return await self._parse_result(result_data)

    # ------------------------------------------------------------------
    # Job submission
    # ------------------------------------------------------------------

    async def _submit_job(self, image_bytes: bytes, filename: str) -> str:
        """Submit an OCR job via multipart upload. Returns job_id."""
        url = f"{self._base_url}/api/v2/ocr/jobs"
        headers = {"Authorization": f"bearer {self._api_token}"}

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                url,
                headers=headers,
                files={"file": (filename, image_bytes, "image/png")},
                data={"model": self._model},
            )
            _raise_on_bad_status(response)
            body = _parse_json_body(response)
            job_id = body.get("jobId") or body.get("id")
            if not job_id:
                raise JobSubmissionError(
                    f"No job_id in response: {json.dumps(body, ensure_ascii=False)[:200]}"
                )
            return str(job_id)

    async def _submit_url_job(self, file_url: str) -> str:
        """Submit an OCR job via URL. Returns job_id."""
        url = f"{self._base_url}/api/v2/ocr/jobs"
        headers = {
            "Authorization": f"bearer {self._api_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "fileUrl": file_url,
            "model": self._model,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, headers=headers, json=payload)
            _raise_on_bad_status(response)
            body = _parse_json_body(response)
            job_id = body.get("jobId") or body.get("id")
            if not job_id:
                raise JobSubmissionError(
                    f"No job_id in URL submission response: "
                    f"{json.dumps(body, ensure_ascii=False)[:200]}"
                )
            return str(job_id)

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
        """Generic retry wrapper for job submission."""
        last_error: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                return await submit_fn()
            except (JobSubmissionError, httpx.TimeoutException) as exc:
                last_error = exc
                logger.warning(
                    "PaddleOCR-VL %s attempt %d/%d failed: %s",
                    desc, attempt + 1, self._max_retries, exc,
                )
                if attempt < self._max_retries - 1:
                    await asyncio.sleep(_RETRY_DELAY * (attempt + 1))
        raise JobSubmissionError(
            f"All {self._max_retries} {desc} attempts failed: {last_error}"
        ) from last_error

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    async def _poll_job_status(self, job_id: str) -> dict:
        """Poll the job status once. Returns the response dict."""
        url = f"{self._base_url}/api/v2/ocr/jobs/{job_id}"
        headers = {"Authorization": f"bearer {self._api_token}"}

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, headers=headers)
            if response.status_code != 200:
                raise JobPollingError(
                    f"Poll HTTP {response.status_code}: {response.text[:200]}"
                )
            return _parse_json_body(response)

    async def _poll_with_timeout(self, job_id: str) -> dict:
        """Poll until done/failed or timeout. Returns the result data dict."""
        deadline = time.monotonic() + self._poll_timeout
        last_status: str | None = None

        while True:
            remaining = deadline - time.monotonic()

            if remaining <= 0:
                raise JobPollingError(
                    f"Job {job_id} polling timed out after {self._poll_timeout}s "
                    f"(last status: {last_status})"
                )

            try:
                body = await self._poll_job_status(job_id)
            except (JobPollingError, httpx.TimeoutException) as exc:
                logger.warning("Poll job %s failed, retrying: %s", job_id, exc)
                await asyncio.sleep(self._poll_interval)
                continue

            status = (body.get("status") or "").lower()
            last_status = status

            if status == "done":
                return body
            if status == "failed":
                error_msg = body.get("error") or body.get("message") or "unknown error"
                raise JobPollingError(f"Job {job_id} failed: {error_msg}")

            # still pending/running — wait and retry
            await asyncio.sleep(self._poll_interval)

    # ------------------------------------------------------------------
    # Result parsing
    # ------------------------------------------------------------------

    async def _parse_result(self, job_data: dict) -> PaddleOCRVLResult:
        """Download and parse the OCR result from resultUrl.jsonUrl."""
        json_url = _extract_result_url(job_data)

        raw_text, confidence = await self._download_and_parse_jsonl(json_url)
        return PaddleOCRVLResult(
            text=raw_text,
            confidence=confidence,
            raw={"job_data": job_data, "result_url": json_url},
        )

    async def _download_and_parse_jsonl(self, url: str) -> tuple[str, float]:
        """Download JSONL from url and extract concatenated text + avg confidence."""
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url)
            response.raise_for_status()
            raw = response.text

        lines = [l.strip() for l in raw.split("\n") if l.strip()]
        if not lines:
            return "", 0.0

        text_parts: list[str] = []
        confidences: list[float] = []

        for line in lines:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

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

        full_text = "\n".join(text_parts)
        avg_confidence = (
            round(sum(confidences) / len(confidences), 4) if confidences else 0.0
        )
        return full_text, avg_confidence
