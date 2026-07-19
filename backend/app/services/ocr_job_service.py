"""OCR Job service — database-backed control plane for thin production + local GPU worker.

Design principles:
- No Redis, Celery, or Kafka — uses the existing database for persistence.
- Atomic claim via single UPDATE with WHERE conditions (no SELECT-then-UPDATE race).
- Lease token is SHA256-hashed in DB; raw token returned only at claim time.
- Retry with exponential backoff: 30s, 2min, 10min (max 3 attempts).
- Idempotent creation via request_id unique constraint.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ocr_job import OCRJob
from app.models.pipeline_enums import (
    OCRJobStatus,
    guard_ocr_job_transition,
)

# ── Constants ─────────────────────────────────────────────
DEFAULT_LEASE_SECONDS: int = 300  # 5 minutes
DEFAULT_HEARTBEAT_SECONDS: int = 45
DEFAULT_MAX_ATTEMPTS: int = 3

# Retry backoff: attempt 1 → 30s, attempt 2 → 120s, attempt 3 → 600s
RETRY_BACKOFF_SECONDS: list[int] = [30, 120, 600]

# Error codes that are NEVER retryable
NON_RETRYABLE_ERROR_CODES: set[str] = {
    "INVALID_INPUT",
    "UNSUPPORTED_MIME",
    "INPUT_HASH_MISMATCH",
    "DOCUMENT_IR_INVALID",
    "SCHEMA_INCOMPATIBLE",
    "ENCRYPTED_PDF_UNSUPPORTED",
}


# ── Helpers ───────────────────────────────────────────────

def _generate_id() -> str:
    return secrets.token_hex(16)  # 32 hex chars


def _generate_lease_token() -> str:
    return secrets.token_hex(32)  # 64 hex chars


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _compute_retry_at(attempt: int) -> datetime:
    """Compute next_retry_at based on attempt number (0-indexed)."""
    if attempt < 0 or attempt >= len(RETRY_BACKOFF_SECONDS):
        return _now() + timedelta(seconds=RETRY_BACKOFF_SECONDS[-1])
    return _now() + timedelta(seconds=RETRY_BACKOFF_SECONDS[attempt])


# ── Core Service ──────────────────────────────────────────

async def create_job(
    db: AsyncSession,
    *,
    request_id: str,
    document_id: str,
    document_sha256: str,
    input_artifact_key: str,
    input_mime_type: str,
    input_size_bytes: int,
    pipeline_fingerprint: str,
    input_page_count: int | None = None,
    required_document_ir_schema: str = "1.0",
    priority: int = 0,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> OCRJob:
    """Create a new OCR job. Idempotent on request_id — returns existing job if found.

    Raises ValueError if input validation fails.
    """
    # Check for existing job with same request_id (idempotency)
    existing = await db.execute(
        select(OCRJob).where(OCRJob.request_id == request_id)
    )
    existing_job = existing.scalar_one_or_none()
    if existing_job is not None:
        return existing_job

    job = OCRJob(
        id=_generate_id(),
        request_id=request_id,
        document_id=document_id,
        document_sha256=document_sha256,
        status=OCRJobStatus.PENDING.value,
        priority=priority,
        input_artifact_key=input_artifact_key,
        input_mime_type=input_mime_type,
        input_size_bytes=input_size_bytes,
        input_page_count=input_page_count,
        pipeline_fingerprint=pipeline_fingerprint,
        required_document_ir_schema=required_document_ir_schema,
        max_attempts=max_attempts,
    )
    db.add(job)
    await db.flush()
    return job


async def claim_job(
    db: AsyncSession,
    *,
    worker_id: str,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> tuple[OCRJob, str] | None:
    """Atomically claim the next available OCR job.

    Finds a PENDING or RETRYABLE job where:
    - next_retry_at IS NULL or <= now
    - lease is not held by another worker (lease_expires_at IS NULL or expired)

    Returns (job, raw_lease_token) or None if no job available.

    Uses a single UPDATE with subquery for atomicity (avoids race conditions).
    """
    now = _now()
    lease_expires_at = now + timedelta(seconds=lease_seconds)
    lease_token = _generate_lease_token()
    token_hash = _hash_token(lease_token)

    # Subquery: find the highest-priority claimable job
    # Use UPDATE ... FROM (SELECT ...) for atomic claim
    subq = (
        select(OCRJob.id)
        .where(
            OCRJob.status.in_([
                OCRJobStatus.PENDING.value,
                OCRJobStatus.RETRYABLE.value,
            ])
        )
        .where(
            (OCRJob.next_retry_at.is_(None))
            | (OCRJob.next_retry_at <= now)
        )
        .where(
            (OCRJob.lease_expires_at.is_(None))
            | (OCRJob.lease_expires_at <= now)
        )
        .order_by(OCRJob.priority.desc(), OCRJob.created_at.asc())
        .limit(1)
        .cte("claimable")
    )

    # Single atomic UPDATE
    result = await db.execute(
        select(OCRJob)
        .where(OCRJob.id.in_(select(subq.c.id)))
        .with_for_update(skip_locked=True)
    )
    job = result.scalar_one_or_none()
    if job is None:
        return None

    guard_ocr_job_transition(job.status, OCRJobStatus.LEASED.value)

    job.status = OCRJobStatus.LEASED.value
    job.lease_owner = worker_id
    job.lease_token_hash = token_hash
    job.lease_expires_at = lease_expires_at
    job.heartbeat_at = now
    job.attempt_count += 1
    await db.flush()

    return job, lease_token


async def heartbeat(
    db: AsyncSession,
    job_id: str,
    lease_token: str,
    *,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> OCRJob:
    """Extend lease on a claimed job.

    Validates lease token hash. Raises ValueError on token mismatch or invalid state.
    Returns the updated job.
    """
    job = await _get_job_or_raise(db, job_id)
    _verify_lease(job, lease_token)

    now = _now()
    job.heartbeat_at = now
    job.lease_expires_at = now + timedelta(seconds=lease_seconds)
    await db.flush()
    return job


async def start_job(
    db: AsyncSession,
    job_id: str,
    lease_token: str,
    *,
    worker_fingerprint: str | None = None,
    model_fingerprint: str | None = None,
) -> OCRJob:
    """Mark job as running (downloading → running)."""
    job = await _get_job_or_raise(db, job_id)
    _verify_lease(job, lease_token)

    guard_ocr_job_transition(job.status, OCRJobStatus.RUNNING.value)
    job.status = OCRJobStatus.RUNNING.value
    job.started_at = _now()
    if worker_fingerprint is not None:
        job.worker_fingerprint = worker_fingerprint
    if model_fingerprint is not None:
        job.model_fingerprint = model_fingerprint
    await db.flush()
    return job


async def complete_job(
    db: AsyncSession,
    job_id: str,
    lease_token: str,
    *,
    output_artifact_key: str,
    output_sha256: str,
    worker_fingerprint: str | None = None,
    model_fingerprint: str | None = None,
    complete_idempotency_key: str | None = None,
) -> OCRJob:
    """Mark job as completed with output artifact.

    Idempotent: if already COMPLETED with same idempotency_key, returns existing job.
    Raises ValueError on lease token mismatch or invalid state.
    """
    job = await _get_job_or_raise(db, job_id)

    # Idempotent re-completion check
    if job.status == OCRJobStatus.COMPLETED.value:
        if complete_idempotency_key and job.complete_idempotency_key == complete_idempotency_key:
            return job
        if job.output_sha256 == output_sha256:
            return job
        raise ValueError(
            f"Job {job_id} already completed with a different output"
        )

    _verify_lease(job, lease_token)
    guard_ocr_job_transition(job.status, OCRJobStatus.COMPLETED.value)

    job.status = OCRJobStatus.COMPLETED.value
    job.output_artifact_key = output_artifact_key
    job.output_sha256 = output_sha256
    job.completed_at = _now()
    job.lease_expires_at = None
    job.lease_token_hash = None
    job.heartbeat_at = None
    if complete_idempotency_key is not None:
        job.complete_idempotency_key = complete_idempotency_key
    if worker_fingerprint is not None:
        job.worker_fingerprint = worker_fingerprint
    if model_fingerprint is not None:
        job.model_fingerprint = model_fingerprint
    await db.flush()
    return job


async def fail_job(
    db: AsyncSession,
    job_id: str,
    lease_token: str,
    *,
    error_code: str,
    error_message: str = "",
    is_retryable: bool = True,
    worker_fingerprint: str | None = None,
) -> OCRJob:
    """Mark job as failed.

    If is_retryable and attempt_count < max_attempts, transitions to RETRYABLE.
    If error_code is in NON_RETRYABLE_ERROR_CODES, forces is_retryable=False.
    Otherwise transitions to FAILED.
    """
    job = await _get_job_or_raise(db, job_id)
    _verify_lease(job, lease_token)

    # Force non-retryable for known unrecoverable errors
    if error_code in NON_RETRYABLE_ERROR_CODES:
        is_retryable = False

    if is_retryable and job.attempt_count < job.max_attempts:
        target_status = OCRJobStatus.RETRYABLE.value
    else:
        target_status = (
            OCRJobStatus.DEAD_LETTER.value
            if is_retryable and job.attempt_count >= job.max_attempts
            else OCRJobStatus.FAILED.value
        )

    guard_ocr_job_transition(job.status, target_status)
    job.status = target_status
    job.last_error_code = error_code
    job.last_error_message = error_message[:1024]
    job.completed_at = _now()
    job.lease_token_hash = None
    job.lease_expires_at = None

    if target_status == OCRJobStatus.RETRYABLE.value:
        job.next_retry_at = _compute_retry_at(job.attempt_count - 1)

    if worker_fingerprint is not None:
        job.worker_fingerprint = worker_fingerprint

    await db.flush()
    return job


async def release_job(
    db: AsyncSession,
    job_id: str,
    lease_token: str,
) -> OCRJob:
    """Release a claimed job back to PENDING (e.g., worker crashing, graceful shutdown).

    Only valid from LEASED state. Clears lease fields without advancing attempt_count.
    """
    job = await _get_job_or_raise(db, job_id)
    _verify_lease(job, lease_token)

    if job.status == OCRJobStatus.LEASED.value:
        job.status = OCRJobStatus.PENDING.value
        job.lease_owner = None
        job.lease_token_hash = None
        job.lease_expires_at = None
        job.heartbeat_at = None
        job.attempt_count = max(0, job.attempt_count - 1)  # undo the claim increment
        await db.flush()

    return job


async def cancel_job(
    db: AsyncSession,
    job_id: str,
) -> OCRJob:
    """Cancel a job. Only valid from PENDING or LEASED states."""
    job = await _get_job_or_raise(db, job_id)

    guard_ocr_job_transition(job.status, OCRJobStatus.CANCELLED.value)
    job.status = OCRJobStatus.CANCELLED.value
    job.lease_token_hash = None
    job.lease_expires_at = None
    job.completed_at = _now()
    await db.flush()
    return job


async def get_job(
    db: AsyncSession,
    job_id: str,
) -> OCRJob | None:
    """Get a single job by ID."""
    return await db.get(OCRJob, job_id)


async def list_jobs(
    db: AsyncSession,
    *,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[OCRJob], int]:
    """List jobs with optional status filter and pagination."""
    query = select(OCRJob)
    count_query = select(func.count(OCRJob.id))

    if status is not None:
        query = query.where(OCRJob.status == status)
        count_query = count_query.where(OCRJob.status == status)

    # Get total count
    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    # Get paginated results
    query = query.order_by(OCRJob.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    jobs = list(result.scalars().all())

    return jobs, total


# ── Internal ──────────────────────────────────────────────

async def _get_job_or_raise(db: AsyncSession, job_id: str) -> OCRJob:
    """Get job by ID or raise ValueError."""
    job = await db.get(OCRJob, job_id)
    if job is None:
        raise ValueError(f"OCR job not found: {job_id}")
    return job


def _verify_lease(job: OCRJob, lease_token: str) -> None:
    """Verify lease token hash matches. Raise ValueError on mismatch.

    Also checks that lease has not expired.
    """
    if job.lease_token_hash is None:
        raise ValueError(
            f"Job {job.id} has no active lease (status={job.status})"
        )

    if _hash_token(lease_token) != job.lease_token_hash:
        raise ValueError(
            f"Lease token mismatch for job {job.id}"
        )

    # Warn but don't reject expired leases — the caller can decide.
    # The claim mechanism will eventually reclaim expired leases.
    if job.lease_expires_at is not None and _now() > job.lease_expires_at:
        raise ValueError(
            f"Lease expired for job {job.id} at {job.lease_expires_at.isoformat()}"
        )
