"""OCR Job model + service tests — inline DB setup matching project test patterns."""

from __future__ import annotations

import os
import uuid

# Use shared test DB from conftest if already set; otherwise create unique one
_TEST_DB_PATH = f"/tmp/_test_ocr_jobs_{uuid.uuid4().hex[:8]}.db"
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{_TEST_DB_PATH}")

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session, engine
from app.models.ocr_job import OCRJob
from app.models.pipeline_enums import OCRJobStatus
from app.services.ocr_job_service import (
    cancel_job,
    claim_job,
    complete_job,
    create_job,
    fail_job,
    get_job,
    heartbeat,
    list_jobs,
    release_job,
    start_job,
)

# ── Constants & Helpers ───────────────────────────────────

_SAMPLE_DOC_SHA = "a" * 64
_SAMPLE_OUTPUT_SHA = "b" * 64

_initialized = False


async def _ensure_table():
    global _initialized
    if not _initialized:
        async with engine.begin() as conn:
            await conn.run_sync(OCRJob.__table__.create, checkfirst=True)
        _initialized = True


async def _make_job(db: AsyncSession, **overrides) -> OCRJob:
    await _ensure_table()
    params = dict(
        request_id=f"req-{uuid.uuid4().hex[:8]}",
        document_id="doc-001",
        document_sha256=_SAMPLE_DOC_SHA,
        input_artifact_key="uploads/test.pdf",
        input_mime_type="application/pdf",
        input_size_bytes=1024,
        pipeline_fingerprint="pipe-v1",
    )
    params.update(overrides)
    return await create_job(db, **params)


@pytest_asyncio.fixture(autouse=True)
async def _clean_ocr_jobs():
    """Clear the ocr_jobs table before each test.

    DATABASE_URL uses setdefault so the engine is shared with whichever module
    set it first; other modules may commit ocr_jobs rows that leak into this
    file's empty-state assertions. Delete them per-test so ordering can't matter.
    """
    await _ensure_table()
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM ocr_jobs"))
    yield


# ── Tests ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_job_sets_defaults():
    async with async_session() as db:
        job = await _make_job(db)
        assert job.status == OCRJobStatus.PENDING.value
        assert job.max_attempts == 3
        assert job.attempt_count == 0
        assert job.priority == 0
        assert job.lease_owner is None
        assert job.lease_token_hash is None
        assert job.output_artifact_key is None


@pytest.mark.asyncio
async def test_create_job_idempotent():
    async with async_session() as db:
        job1 = await _make_job(db, request_id="dup-req")
        job2 = await _make_job(db, request_id="dup-req")
        assert job1.id == job2.id


@pytest.mark.asyncio
async def test_create_job_different_request_id():
    async with async_session() as db:
        j1 = await _make_job(db, request_id="req-a")
        j2 = await _make_job(db, request_id="req-b")
        assert j1.id != j2.id


@pytest.mark.asyncio
async def test_job_fields_match_input():
    async with async_session() as db:
        job = await _make_job(db, request_id="req-field", document_id="doc-field",
                              input_page_count=5, priority=10, max_attempts=5)
        assert job.document_id == "doc-field"
        assert job.input_page_count == 5
        assert job.priority == 10
        assert job.max_attempts == 5


@pytest.mark.asyncio
async def test_claim_none_when_empty():
    async with async_session() as db:
        result = await claim_job(db, worker_id="w1")
        assert result is None


@pytest.mark.asyncio
async def test_claim_returns_pending():
    async with async_session() as db:
        await _make_job(db)
        result = await claim_job(db, worker_id="w1")
        assert result is not None
        job, token = result
        assert job.status == OCRJobStatus.LEASED.value
        assert job.lease_owner == "w1"
        assert len(token) == 64


@pytest.mark.asyncio
async def test_claim_rejects_already_leased():
    async with async_session() as db:
        await _make_job(db)
        await claim_job(db, worker_id="w1")
        result = await claim_job(db, worker_id="w2")
        assert result is None


@pytest.mark.asyncio
async def test_claim_respects_priority():
    async with async_session() as db:
        await _make_job(db, request_id="low", priority=0)
        await _make_job(db, request_id="high", priority=10)
        result = await claim_job(db, worker_id="w1")
        assert result is not None
        job, _ = result
        assert job.priority == 10


@pytest.mark.asyncio
async def test_claim_retryable():
    async with async_session() as db:
        job = await _make_job(db)
        job.status = OCRJobStatus.RETRYABLE.value
        job.next_retry_at = None
        await db.flush()
        result = await claim_job(db, worker_id="w1")
        assert result is not None


@pytest.mark.asyncio
async def test_heartbeat_extends_lease():
    async with async_session() as db:
        await _make_job(db)
        job, token = await claim_job(db, worker_id="w1")
        old_expiry = job.lease_expires_at
        refreshed = await heartbeat(db, job.id, token, lease_seconds=600)
        if old_expiry is not None and refreshed.lease_expires_at is not None:
            assert refreshed.lease_expires_at > old_expiry


@pytest.mark.asyncio
async def test_heartbeat_wrong_token_raises():
    async with async_session() as db:
        await _make_job(db)
        job, _ = await claim_job(db, worker_id="w1")
        with pytest.raises(ValueError, match="Lease token mismatch"):
            await heartbeat(db, job.id, "bad-token")


@pytest.mark.asyncio
async def test_start_job_transitions():
    async with async_session() as db:
        await _make_job(db)
        job, token = await claim_job(db, worker_id="w1")
        job.status = OCRJobStatus.DOWNLOADING.value
        await db.flush()
        started = await start_job(db, job.id, token,
                                  worker_fingerprint="wv1", model_fingerprint="ppv4")
        assert started.status == OCRJobStatus.RUNNING.value
        assert started.worker_fingerprint == "wv1"


@pytest.mark.asyncio
async def test_complete_happy_path():
    async with async_session() as db:
        await _make_job(db)
        job, token = await claim_job(db, worker_id="w1")
        job.status = OCRJobStatus.UPLOADING.value
        await db.flush()
        completed = await complete_job(db, job.id, token,
                                        output_artifact_key="out.json",
                                        output_sha256=_SAMPLE_OUTPUT_SHA)
        assert completed.status == OCRJobStatus.COMPLETED.value


@pytest.mark.asyncio
async def test_complete_idempotent():
    async with async_session() as db:
        await _make_job(db)
        job, token = await claim_job(db, worker_id="w1")
        job.status = OCRJobStatus.UPLOADING.value
        await db.flush()
        c1 = await complete_job(db, job.id, token,
                                 output_artifact_key="out.json",
                                 output_sha256=_SAMPLE_OUTPUT_SHA,
                                 complete_idempotency_key="ik-001")
        assert c1.status == OCRJobStatus.COMPLETED.value
        c2 = await complete_job(db, job.id, token,
                                 output_artifact_key="out.json",
                                 output_sha256=_SAMPLE_OUTPUT_SHA,
                                 complete_idempotency_key="ik-001")
        assert c2.status == OCRJobStatus.COMPLETED.value


@pytest.mark.asyncio
async def test_complete_different_output_raises():
    async with async_session() as db:
        await _make_job(db)
        job, token = await claim_job(db, worker_id="w1")
        job.status = OCRJobStatus.UPLOADING.value
        await db.flush()
        await complete_job(db, job.id, token,
                            output_artifact_key="out.json",
                            output_sha256=_SAMPLE_OUTPUT_SHA)
        with pytest.raises(ValueError, match="already completed"):
            await complete_job(db, job.id, token,
                                output_artifact_key="diff.json",
                                output_sha256="d" * 64)


@pytest.mark.asyncio
async def test_fail_retryable():
    async with async_session() as db:
        await _make_job(db, max_attempts=3)
        job, token = await claim_job(db, worker_id="w1")
        job.status = OCRJobStatus.RUNNING.value
        await db.flush()
        failed = await fail_job(db, job.id, token,
                                 error_code="NETWORK_ERROR",
                                 error_message="timeout", is_retryable=True)
        assert failed.status == OCRJobStatus.RETRYABLE.value
        assert failed.next_retry_at is not None


@pytest.mark.asyncio
async def test_fail_non_retryable():
    async with async_session() as db:
        await _make_job(db)
        job, token = await claim_job(db, worker_id="w1")
        job.status = OCRJobStatus.RUNNING.value
        await db.flush()
        failed = await fail_job(db, job.id, token,
                                 error_code="DOCUMENT_IR_INVALID",
                                 error_message="bad schema", is_retryable=True)
        assert failed.status == OCRJobStatus.FAILED.value


@pytest.mark.asyncio
async def test_fail_exhausts_retries():
    async with async_session() as db:
        await _make_job(db, max_attempts=1)
        job, token = await claim_job(db, worker_id="w1")
        job.status = OCRJobStatus.RUNNING.value
        await db.flush()
        failed = await fail_job(db, job.id, token,
                                 error_code="NETWORK_ERROR",
                                 error_message="fail", is_retryable=True)
        assert failed.status == OCRJobStatus.DEAD_LETTER.value


@pytest.mark.asyncio
async def test_cancel_pending():
    async with async_session() as db:
        job = await _make_job(db)
        cancelled = await cancel_job(db, job.id)
        assert cancelled.status == OCRJobStatus.CANCELLED.value


@pytest.mark.asyncio
async def test_cancel_leased():
    async with async_session() as db:
        await _make_job(db)
        job, _ = await claim_job(db, worker_id="w1")
        cancelled = await cancel_job(db, job.id)
        assert cancelled.status == OCRJobStatus.CANCELLED.value


@pytest.mark.asyncio
async def test_cancel_completed_raises():
    async with async_session() as db:
        await _make_job(db)
        job, token = await claim_job(db, worker_id="w1")
        job.status = OCRJobStatus.UPLOADING.value
        await db.flush()
        await complete_job(db, job.id, token,
                            output_artifact_key="out.json",
                            output_sha256=_SAMPLE_OUTPUT_SHA)
        with pytest.raises(ValueError, match="Invalid OCR job status transition"):
            await cancel_job(db, job.id)


@pytest.mark.asyncio
async def test_get_job_missing():
    async with async_session() as db:
        job = await get_job(db, "nonexistent")
        assert job is None


@pytest.mark.asyncio
async def test_get_job_found():
    async with async_session() as db:
        created = await _make_job(db)
        fetched = await get_job(db, created.id)
        assert fetched is not None
        assert fetched.id == created.id


@pytest.mark.asyncio
async def test_list_jobs_empty():
    async with async_session() as db:
        await db.execute(text("DELETE FROM ocr_jobs"))
        await db.commit()
        jobs, total = await list_jobs(db)
        assert jobs == []
        assert total == 0


@pytest.mark.asyncio
async def test_list_jobs_with_data():
    async with async_session() as db:
        await db.execute(text("DELETE FROM ocr_jobs"))
        await db.commit()
        await _make_job(db, request_id="a")
        await _make_job(db, request_id="b")
        jobs, total = await list_jobs(db)
        assert total == 2


@pytest.mark.asyncio
async def test_list_jobs_filter_by_status():
    async with async_session() as db:
        await db.execute(text("DELETE FROM ocr_jobs"))
        await db.commit()
        await _make_job(db, request_id="a")
        j2 = await _make_job(db, request_id="b")
        j2.status = OCRJobStatus.LEASED.value
        await db.flush()
        jobs, total = await list_jobs(db, status=OCRJobStatus.LEASED.value)
        assert total == 1
        assert jobs[0].id == j2.id


@pytest.mark.asyncio
async def test_stale_lease_cannot_complete():
    async with async_session() as db:
        await _make_job(db)
        job, _ = await claim_job(db, worker_id="w1")
        job.status = OCRJobStatus.UPLOADING.value
        await db.flush()
        with pytest.raises(ValueError, match="Lease token mismatch"):
            await complete_job(db, job.id, "bad-token",
                                output_artifact_key="out.json",
                                output_sha256=_SAMPLE_OUTPUT_SHA)


@pytest.mark.asyncio
async def test_release_returns_to_pending():
    async with async_session() as db:
        await _make_job(db)
        job, token = await claim_job(db, worker_id="w1")
        released = await release_job(db, job.id, token)
        assert released.status == OCRJobStatus.PENDING.value
        assert released.lease_owner is None
        assert released.lease_token_hash is None


@pytest.mark.asyncio
async def test_completed_job_cannot_be_claimed():
    async with async_session() as db:
        await _make_job(db)
        job, token = await claim_job(db, worker_id="w1")
        job.status = OCRJobStatus.UPLOADING.value
        await db.flush()
        await complete_job(db, job.id, token,
                            output_artifact_key="out.json",
                            output_sha256=_SAMPLE_OUTPUT_SHA)
        result = await claim_job(db, worker_id="w2")
        assert result is None


@pytest.mark.asyncio
async def test_hash_token_consistency():
    from app.services.ocr_job_service import _hash_token
    h1 = _hash_token("my-token")
    h2 = _hash_token("my-token")
    assert h1 == h2
    assert len(h1) == 64


def _cleanup():
    global _initialized
    _initialized = False
    try:
        os.remove(_TEST_DB_PATH)
    except OSError:
        pass


# Register cleanup at end of module
import atexit

atexit.register(_cleanup)
