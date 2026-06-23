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
from urllib.parse import urljoin

import httpx

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
    """Raise JobSubmissionError if HTTP status is not 200."""
    if response.status_code != 200:
        raise JobSubmissionError(
            f"PaddleOCR-VL HTTP {response.status_code}: {response.text[:200]}"
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

# Defaults
_DEFAULT_BASE_URL = "https://paddleocr.aistudio-app.com"
_OCR_VL_API_PATH = "/api/v2/ocr/jobs"   # endpoint path used by urljoin
_DEFAULT_POLL_INTERVAL = 5.0  # seconds between polls (官方建议 ≥5s)
_DEFAULT_POLL_TIMEOUT = 120  # max total poll time
_MAX_RETRIES = 3
_RETRY_DELAY = 2.0  # seconds between retries


class PaddleOCRVLClientError(Exception):
    """Base exception for PaddleOCR-VL client errors."""


class JobSubmissionError(PaddleOCRVLClientError):
    """Failed to submit an OCR job (transient — caller may retry)."""


class JobPollingError(PaddleOCRVLClientError):
    """Job polling failed or timed out."""


class ResultDownloadError(PaddleOCRVLClientError):
    """Failed to download or parse the OCR result."""


class ContractError(PaddleOCRVLClientError):
    """API response contract mismatch (non-transient — do NOT retry)."""


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
        url = urljoin(self._base_url, _OCR_VL_API_PATH)
        logger.info("PaddleOCR-VL submit_job url=%s", url)
        headers = {"Authorization": f"Bearer {self._api_token}"}

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                url,
                headers=headers,
                files={"file": (filename, image_bytes, "image/png")},
                data={"model": self._model},
            )
            _raise_on_bad_status(response)
            body = _parse_json_body(response)
            logger.info("[PaddleOCR-VL] submit raw response: %s",
                        json.dumps(body, ensure_ascii=False)[:500])
            data = _unwrap_data(body)
            job_id = _extract_job_id(data)
            logger.info("[PaddleOCR-VL] extracted job_id=%s", job_id)
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

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, headers=headers, json=payload)
            _raise_on_bad_status(response)
            body = _parse_json_body(response)
            logger.info("[PaddleOCR-VL] submit_url raw response: %s",
                        json.dumps(body, ensure_ascii=False)[:500])
            data = _unwrap_data(body)
            job_id = _extract_job_id(data)
            logger.info("[PaddleOCR-VL] extracted job_id=%s", job_id)
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

        Only retries transient failures:
          - HTTP status != 200
          - API code != 0
          - network / timeout exceptions

        Does NOT retry ``ContractError`` (API contract mismatch) —
        those are non-transient and should fail fast.
        """
        last_error: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                return await submit_fn()
            except ContractError:
                # Non-transient — fail immediately, do not retry
                raise
            except (JobSubmissionError, httpx.TimeoutException) as exc:
                last_error = exc
                logger.warning(
                    "PaddleOCR-VL %s attempt %d/%d failed: %s",
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

        async with httpx.AsyncClient(timeout=30) as client:
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
                    f"Job {job_id} poll response missing 'data': "
                    f"{json.dumps(body, ensure_ascii=False)[:200]}"
                )
            logger.info(
                "[PaddleOCR-VL] poll job=%s response data=%s",
                job_id, json.dumps(data, ensure_ascii=False)[:500],
            )
            return data

    async def _poll_with_timeout(self, job_id: str) -> dict:
        """Poll until done/failed or timeout. Returns the result data dict."""
        deadline = time.monotonic() + self._poll_timeout
        last_status: str | None = None

        # 首次轮询前等待 5s，避免 API 还没开始处理就狂刷
        await asyncio.sleep(5)

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

            status = (body.get("status") or body.get("state") or "").lower()
            last_status = status

            if status in ("done", "completed", "success", "finished"):
                return body
            if status in ("failed", "error"):
                error_msg = body.get("errorMsg") or body.get("error") or body.get("message") or "unknown error"
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
        """Download JSONL from url and extract concatenated text + avg confidence.

        JSONL 格式（PaddleOCR-VL）:
            {"result": {"layoutParsingResults": [{"markdown": {"text": "..."}, ...}]}}
        """
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

            # 提取 result.layoutParsingResults[].markdown.text（PaddleOCR-VL 格式）
            result_data = entry.get("result") or entry
            layout_results = result_data.get("layoutParsingResults") if isinstance(result_data, dict) else None
            if isinstance(layout_results, list):
                for lr in layout_results:
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
                continue

            # 兜底：顶层 text/ocr_text/content 字段
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
