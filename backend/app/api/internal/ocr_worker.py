"""Internal Worker API router — for local GPU OCR worker machine-to-machine auth.

Worker authentication:
- Uses `Worker-API-Key` header validated against database-stored hashed credentials.
- Fallback to `settings.INTERNAL_API_KEY` when DB credentials not yet set up.
- Keys are never stored in plaintext — only SHA-256 hashes.
- Supports per-worker key rotation and active/disabled state.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.schemas.ocr_job import (
    OCRClaimResponse,
    OCRCompleteRequest,
    OCRFailRequest,
    OCRHeartbeatRequest,
    OCRJobListResponse,
    OCRJobResponse,
    OCRStartRequest,
)
from app.services import ocr_job_service as svc
from app.services.worker_credential_service import (
    constant_time_compare,
    hash_key,
    verify_credential,
)

logger = logging.getLogger("postgraduate-ai.internal.ocr-worker")

router = APIRouter(prefix="/api/internal/ocr-worker", tags=["ocr-worker"])


# ── Auth dependency ───────────────────────────────────────

async def verify_worker_api_key(
    worker_api_key: Annotated[str | None, Header(alias="Worker-API-Key")] = None,
    db: AsyncSession = Depends(get_db),
) -> str:
    """Verify the Worker-API-Key header.

    Database-backed verification (preferred) — checks hashed credentials.
    Falls back to INTERNAL_API_KEY / APP_SECRET when DB is unavailable.

    Returns worker_id on success, raises 401 on failure.
    """
    if not worker_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Worker-API-Key header",
        )

    # Extract worker_id from "worker-id/token" format
    if "/" in worker_api_key:
        worker_id, token = worker_api_key.split("/", 1)
    else:
        worker_id = "unknown"
        token = worker_api_key

    # 1. Try database-backed credential verification
    try:
        matched = await verify_credential(db, worker_id, token)
        if matched is not None:
            return worker_id
    except Exception as exc:
        logger.warning("DB credential verification unavailable, falling back: %s", exc)

    # 2. Fallback: check against INTERNAL_API_KEY / APP_SECRET
    expected = settings.INTERNAL_API_KEY or settings.APP_SECRET
    if expected and hash_key(token) == hash_key(expected):
        return worker_id

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid Worker-API-Key",
    )


WorkerAuth = Annotated[str, Depends(verify_worker_api_key)]


# ── Helper ────────────────────────────────────────────────

def _ok(data: object, status_code: int = 200):
    from fastapi.responses import JSONResponse
    return JSONResponse(content={"ok": True, "data": data}, status_code=status_code)


def _err(detail: str, status_code: int = 400):
    raise HTTPException(status_code=status_code, detail=detail)


# ── Endpoints ─────────────────────────────────────────────

@router.post("/jobs/claim")
async def claim_job(
    worker_id: WorkerAuth,
    db: AsyncSession = Depends(get_db),
):
    """Atomically claim the next available OCR job.

    Returns the job details and lease token, or 204 No Content if no job available.
    """
    result = await svc.claim_job(db, worker_id=worker_id)
    if result is None:
        from fastapi.responses import JSONResponse
        return JSONResponse(content={"ok": True, "data": None}, status_code=204)

    job, lease_token = result
    resp = OCRClaimResponse(
        job_id=job.id,
        lease_token=lease_token,
        lease_expires_at=job.lease_expires_at,
        input_artifact_key=job.input_artifact_key,
        input_mime_type=job.input_mime_type,
        input_size_bytes=job.input_size_bytes,
        input_page_count=job.input_page_count,
        required_document_ir_schema=job.required_document_ir_schema,
        pipeline_fingerprint=job.pipeline_fingerprint,
    )
    return _ok(resp.model_dump(mode="json"))


@router.post("/jobs/{job_id}/heartbeat")
async def heartbeat_job(
    job_id: str,
    body: OCRHeartbeatRequest,
    worker_id: WorkerAuth,
    db: AsyncSession = Depends(get_db),
):
    """Extend lease on a claimed job."""
    try:
        job = await svc.heartbeat(db, job_id, body.lease_token)
    except ValueError as e:
        _err(str(e), status_code=status.HTTP_409_CONFLICT)

    return _ok(OCRJobResponse.model_validate(job).model_dump(mode="json"))


@router.post("/jobs/{job_id}/start")
async def start_job(
    job_id: str,
    body: OCRStartRequest,
    worker_id: WorkerAuth,
    db: AsyncSession = Depends(get_db),
):
    """Mark job as running (downloading → running)."""
    try:
        job = await svc.start_job(
            db, job_id, body.lease_token,
            worker_fingerprint=body.worker_fingerprint,
            model_fingerprint=body.model_fingerprint,
        )
    except ValueError as e:
        _err(str(e), status_code=status.HTTP_409_CONFLICT)

    return _ok(OCRJobResponse.model_validate(job).model_dump(mode="json"))


@router.post("/jobs/{job_id}/complete")
async def complete_job(
    job_id: str,
    body: OCRCompleteRequest,
    worker_id: WorkerAuth,
    db: AsyncSession = Depends(get_db),
):
    """Mark job as completed with output artifact."""
    try:
        job = await svc.complete_job(
            db, job_id, body.lease_token,
            output_artifact_key=body.output_artifact_key,
            output_sha256=body.output_sha256,
            worker_fingerprint=body.worker_fingerprint,
            model_fingerprint=body.model_fingerprint,
            complete_idempotency_key=body.complete_idempotency_key,
        )
    except ValueError as e:
        _err(str(e), status_code=status.HTTP_409_CONFLICT)

    return _ok(OCRJobResponse.model_validate(job).model_dump(mode="json"))


@router.post("/jobs/{job_id}/fail")
async def fail_job(
    job_id: str,
    body: OCRFailRequest,
    worker_id: WorkerAuth,
    db: AsyncSession = Depends(get_db),
):
    """Report a job failure."""
    try:
        job = await svc.fail_job(
            db, job_id, body.lease_token,
            error_code=body.error_code,
            error_message=body.error_message,
            is_retryable=body.is_retryable,
            worker_fingerprint=body.worker_fingerprint,
        )
    except ValueError as e:
        _err(str(e), status_code=status.HTTP_409_CONFLICT)

    return _ok(OCRJobResponse.model_validate(job).model_dump(mode="json"))


@router.post("/jobs/{job_id}/release")
async def release_job(
    job_id: str,
    body: OCRHeartbeatRequest,
    worker_id: WorkerAuth,
    db: AsyncSession = Depends(get_db),
):
    """Release a claimed job back to pending."""
    try:
        job = await svc.release_job(db, job_id, body.lease_token)
    except ValueError as e:
        _err(str(e), status_code=status.HTTP_409_CONFLICT)

    return _ok(OCRJobResponse.model_validate(job).model_dump(mode="json"))


@router.get("/jobs/{job_id}")
async def get_job(
    job_id: str,
    worker_id: WorkerAuth,
    db: AsyncSession = Depends(get_db),
):
    """Get job details."""
    job = await svc.get_job(db, job_id)
    if job is None:
        _err("Job not found", status_code=status.HTTP_404_NOT_FOUND)

    return _ok(OCRJobResponse.model_validate(job).model_dump(mode="json"))


@router.get("/jobs")
async def list_jobs(
    worker_id: WorkerAuth,
    status_filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """List OCR jobs with optional status filter and pagination."""
    jobs, total = await svc.list_jobs(
        db, status=status_filter, limit=min(limit, 200), offset=offset
    )
    return _ok(OCRJobListResponse(
        items=[OCRJobResponse.model_validate(j) for j in jobs],
        total=total,
    ).model_dump(mode="json"))
