"""CPU Worker Soak test — multiple sequential jobs, restart and recovery."""
from __future__ import annotations

import os
import uuid

_TEST_DB_PATH = f"/tmp/_test_cpu_soak_{uuid.uuid4().hex[:8]}.db"
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{_TEST_DB_PATH}")

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session, engine
from app.models.ocr_job import OCRJob
from app.models.pipeline_enums import OCRJobStatus
from app.services.ocr_job_service import (
    claim_job,
    complete_job,
    create_job,
    list_jobs,
    start_job,
)

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
        request_id=f"req-soak-{uuid.uuid4().hex[:8]}",
        document_id="doc-soak-001",
        document_sha256=_SAMPLE_DOC_SHA,
        input_artifact_key="tests/soak/sample.png",
        input_mime_type="image/png",
        input_size_bytes=1024,
        pipeline_fingerprint="pipe-soak-v1",
    )
    params.update(overrides)
    return await create_job(db, **params)


async def _run_short_job(db: AsyncSession, worker_id: str = "soak-worker") -> bool:
    """Run a single short job lifecycle. Returns True on success."""
    try:
        job = await _make_job(db)
        result = await claim_job(db, worker_id=worker_id)
        if result is None:
            return False
        job, token = result
        job.status = OCRJobStatus.DOWNLOADING.value
        await db.flush()
        await start_job(db, job.id, token, worker_fingerprint=worker_id)
        job.status = OCRJobStatus.UPLOADING.value
        await db.flush()
        await complete_job(db, job.id, token,
                            output_artifact_key=f"soak/{job.id}.json",
                            output_sha256=_SAMPLE_OUTPUT_SHA)
        return True
    except Exception:
        return False


def _cleanup():
    global _initialized
    _initialized = False
    try:
        os.remove(_TEST_DB_PATH)
    except OSError:
        pass


import atexit

atexit.register(_cleanup)


# Mark the entire soak class as slow by default
pytestmark = pytest.mark.skipif(
    not os.environ.get("STAGE1A_RUN_SOAK", ""),
    reason="Set STAGE1A_RUN_SOAK=1 to run soak tests",
)


class TestCPUWorkerSoak:
    """CPU Worker soak test — multiple sequential jobs."""

    @pytest.mark.asyncio
    async def test_consecutive_small_jobs(self):
        """10 consecutive small jobs to verify stability."""
        async with async_session() as db:
            success_count = 0
            for i in range(10):
                ok = await _run_short_job(db, worker_id="soak-a")
                if ok:
                    success_count += 1
            assert success_count >= 10, f"Only {success_count}/10 succeeded"

    @pytest.mark.asyncio
    async def test_medium_multi_page_jobs(self):
        """3 medium multi-page jobs."""
        async with async_session() as db:
            tasks = []
            for i in range(3):
                tasks.append(_make_job(db,
                    request_id=f"soak-med-{i}",
                    document_id=f"doc-soak-med-{i}",
                    input_page_count=15))

            success_count = 0
            for t in tasks:
                result = await claim_job(db, worker_id="soak-med")
                if result:
                    job, token = result
                    job.status = OCRJobStatus.DOWNLOADING.value
                    await db.flush()
                    await start_job(db, job.id, token,
                                     worker_fingerprint="soak-med")
                    job.status = OCRJobStatus.UPLOADING.value
                    await db.flush()
                    await complete_job(db, job.id, token,
                                        output_artifact_key=f"med/{job.id}.json",
                                        output_sha256=_SAMPLE_OUTPUT_SHA)
                    success_count += 1
            assert success_count == 3, f"Only {success_count}/3 medium jobs succeeded"

    @pytest.mark.asyncio
    async def test_worker_restart_twice(self):
        """Worker restarts 2 times during processing."""
        async with async_session() as db:
            # First round
            for i in range(3):
                await _make_job(db, request_id=f"soak-restart-a-{i}")
            for _ in range(3):
                result = await claim_job(db, worker_id="worker-a")
                if result:
                    job, token = result
                    job.status = OCRJobStatus.UPLOADING.value
                    await db.flush()
                    await complete_job(db, job.id, token,
                                        output_artifact_key=f"ra/{job.id}.json",
                                        output_sha256=_SAMPLE_OUTPUT_SHA)

        # Simulate worker A restart — switch to worker B
        async with async_session() as db:
            for i in range(2):
                await _make_job(db, request_id=f"soak-restart-b-{i}")
            for _ in range(2):
                result = await claim_job(db, worker_id="worker-b")
                if result:
                    job, token = result
                    job.status = OCRJobStatus.UPLOADING.value
                    await db.flush()
                    await complete_job(db, job.id, token,
                                        output_artifact_key=f"rb/{job.id}.json",
                                        output_sha256=_SAMPLE_OUTPUT_SHA)

        # Verify final state
        async with async_session() as db:
            completed, _ = await list_jobs(db, status=OCRJobStatus.COMPLETED.value)
            pending, _ = await list_jobs(db, status=OCRJobStatus.PENDING.value)
            assert len(completed) >= 5  # 3 + 2
            assert pending == 0

    @pytest.mark.asyncio
    async def test_upload_failure_recovery(self):
        """Upload fails then recovers — job completes on retry."""
        async with async_session() as db:
            await _make_job(db, request_id="soak-upload-fail")
            result = await claim_job(db, worker_id="recovery-worker")
            assert result is not None
            job, token = result
            job.status = OCRJobStatus.UPLOADING.value
            await db.flush()

            # "Fail" first attempt — simulate network error
            from app.services.ocr_job_service import fail_job
            job2 = await fail_job(db, job.id, token,
                                   error_code="NETWORK_ERROR",
                                   error_message="upload timeout",
                                   is_retryable=True)
            assert job2.status == OCRJobStatus.RETRYABLE.value

            # Worker re-claims and completes
            result2 = await claim_job(db, worker_id="recovery-worker")
            assert result2 is not None
            job3, token2 = result2
            job3.status = OCRJobStatus.UPLOADING.value
            await db.flush()
            completed = await complete_job(db, job3.id, token2,
                                            output_artifact_key="recovered.json",
                                            output_sha256=_SAMPLE_OUTPUT_SHA)
            assert completed.status == OCRJobStatus.COMPLETED.value
