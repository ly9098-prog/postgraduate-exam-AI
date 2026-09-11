"""OCR Worker API client — communicates with the production server's internal OCR worker API.

All methods raise WorkerClientError on HTTP errors or connection issues.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin

import httpx

from app.ocr_worker.config import OCRWorkerConfig

logger = logging.getLogger("postgraduate-ai.ocr-worker.client")


def parse_iso_timestamp(value: Any, *, fallback: float) -> float:
    if not value:
        return fallback
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.timestamp()
    except (ValueError, TypeError, OverflowError):
        return fallback


class WorkerClientError(Exception):
    """Raised on API client errors (connection, HTTP error, etc.)."""


@dataclass
class ClaimResult:
    """Result of a successful claim."""

    job_id: str
    lease_token: str
    lease_expires_at: float  # Unix timestamp
    input_artifact_key: str
    input_mime_type: str
    input_size_bytes: int
    input_page_count: int | None
    required_document_ir_schema: str
    pipeline_fingerprint: str
    execution_config: dict


class WorkerAPIClient:
    """HTTP client for the production server's internal OCR worker API."""

    def __init__(self, config: OCRWorkerConfig) -> None:
        self._base_url = config.SERVER_URL.rstrip("/")
        self._api_key = config.API_KEY
        self._worker_id = config.WORKER_ID
        self._timeout = httpx.Timeout(30.0, connect=10.0)
        self._client = httpx.Client(
            timeout=self._timeout,
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
        )

    def _headers(self) -> dict[str, str]:
        return {
            "Worker-API-Key": f"{self._worker_id}/{self._api_key}",
            "Content-Type": "application/json",
        }

    def _url(self, path: str) -> str:
        return urljoin(self._base_url + "/", path.lstrip("/"))

    def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        """Make an HTTP request and return parsed JSON response data."""
        try:
            resp = self._client.request(
                method,
                self._url(path),
                headers=self._headers(),
                **kwargs,
            )
        except httpx.RequestError as e:
            raise WorkerClientError(f"Request failed: {e}") from e

        if resp.status_code == 204:
            return {}  # No content

        try:
            body = resp.json()
        except json.JSONDecodeError as e:
            raise WorkerClientError(
                f"Invalid JSON response ({resp.status_code}): {e}"
            ) from e

        if not body.get("ok"):
            detail = body.get("detail", body.get("data", str(resp.text)))
            raise WorkerClientError(f"API error ({resp.status_code}): {detail}")

        return body.get("data", {})

    def close(self) -> None:
        """Close pooled HTTP connections."""
        self._client.close()

    # ── Job lifecycle ────────────────────────────────────

    def claim(self) -> ClaimResult | None:
        """Claim next available OCR job. Returns None if no job available."""
        data = self._request("POST", "/api/internal/ocr-worker/jobs/claim")
        if not data:
            return None

        # Convert lease_expires_at from ISO string to float
        expires_float = parse_iso_timestamp(
            data.get("lease_expires_at"),
            fallback=time.time() + 300,
        )

        return ClaimResult(
            job_id=data["job_id"],
            lease_token=data["lease_token"],
            lease_expires_at=expires_float,
            input_artifact_key=data["input_artifact_key"],
            input_mime_type=data["input_mime_type"],
            input_size_bytes=data["input_size_bytes"],
            input_page_count=data.get("input_page_count"),
            required_document_ir_schema=data.get("required_document_ir_schema", "1.0"),
            pipeline_fingerprint=data.get("pipeline_fingerprint", ""),
            execution_config=data.get("execution_config", {}),
        )

    def heartbeat(self, job_id: str, lease_token: str) -> dict:
        """Send heartbeat to extend lease."""
        return self._request(
            "POST",
            f"/api/internal/ocr-worker/jobs/{job_id}/heartbeat",
            json={"lease_token": lease_token},
        )

    def start(
        self,
        job_id: str,
        lease_token: str,
        worker_fingerprint: str | None = None,
        model_fingerprint: str | None = None,
    ) -> dict:
        """Mark job as started (downloading → running)."""
        body = {"lease_token": lease_token}
        if worker_fingerprint:
            body["worker_fingerprint"] = worker_fingerprint
        if model_fingerprint:
            body["model_fingerprint"] = model_fingerprint
        return self._request(
            "POST",
            f"/api/internal/ocr-worker/jobs/{job_id}/start",
            json=body,
        )

    def complete(
        self,
        job_id: str,
        lease_token: str,
        output_artifact_key: str,
        output_sha256: str,
        worker_fingerprint: str | None = None,
        model_fingerprint: str | None = None,
        complete_idempotency_key: str | None = None,
    ) -> dict:
        """Mark job as completed."""
        body = {
            "lease_token": lease_token,
            "output_artifact_key": output_artifact_key,
            "output_sha256": output_sha256,
        }
        if worker_fingerprint:
            body["worker_fingerprint"] = worker_fingerprint
        if model_fingerprint:
            body["model_fingerprint"] = model_fingerprint
        if complete_idempotency_key:
            body["complete_idempotency_key"] = complete_idempotency_key
        return self._request(
            "POST",
            f"/api/internal/ocr-worker/jobs/{job_id}/complete",
            json=body,
        )

    def fail(
        self,
        job_id: str,
        lease_token: str,
        error_code: str,
        error_message: str = "",
        is_retryable: bool = True,
        worker_fingerprint: str | None = None,
    ) -> dict:
        """Report job failure."""
        body = {
            "lease_token": lease_token,
            "error_code": error_code,
            "error_message": error_message,
            "is_retryable": is_retryable,
        }
        if worker_fingerprint:
            body["worker_fingerprint"] = worker_fingerprint
        return self._request(
            "POST",
            f"/api/internal/ocr-worker/jobs/{job_id}/fail",
            json=body,
        )

    def release(self, job_id: str, lease_token: str) -> dict:
        """Release a claimed job back to pending."""
        return self._request(
            "POST",
            f"/api/internal/ocr-worker/jobs/{job_id}/release",
            json={"lease_token": lease_token},
        )

    def get_job(self, job_id: str) -> dict:
        """Get job details."""
        return self._request(
            "GET",
            f"/api/internal/ocr-worker/jobs/{job_id}",
        )
