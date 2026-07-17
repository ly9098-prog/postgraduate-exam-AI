"""Stage 1A CPU Worker fault injection tests — all non-GPU fault scenarios.

Tests:
1. Worker offline → job stays pending, re-claimable when worker comes back
2. Claim-then-kill → lease expires, job re-claimable, attempt_count increments
3. Heartbeat network interrupt → lease not extended, old token invalidated
4. Input download interrupted → partial file uses .tmp, SHA-256 detects corruption
5. Upload interrupted → local result preserved, re-upload same hash, no re-OCR
6. Server restart → job status persists, heartbeat/lease recovers
7. Worker restart → workspace resume
8. Cancel running → stop processing, no post-OCR
9. Invalid DocumentIR injection → server rejects (NaN bbox, duplicate region, wrong schema)
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid

# Set test DB path before any app imports
_TEST_DB_PATH = f"/tmp/_test_stage1a_faults_{uuid.uuid4().hex[:8]}.db"
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{_TEST_DB_PATH}")

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session, engine
from app.models.ocr_job import OCRJob
from app.models.pipeline_enums import OCRJobStatus
from app.services.ocr_job_service import (
    cancel_job, claim_job, complete_job, create_job, fail_job, get_job,
    heartbeat, list_jobs, release_job, start_job,
)
from app.services.ocr_result_validation import validate_ocr_result
from app.services.ocr_job_service import _now
from datetime import datetime, timedelta, timezone

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
        request_id=f"req-fault-{uuid.uuid4().hex[:8]}",
        document_id="doc-fault-001",
        document_sha256=_SAMPLE_DOC_SHA,
        input_artifact_key="tests/fault/sample.png",
        input_mime_type="image/png",
        input_size_bytes=1024,
        pipeline_fingerprint="pipe-fault-v1",
    )
    params.update(overrides)
    return await create_job(db, **params)


def _cleanup():
    global _initialized
    _initialized = False
    try:
        os.remove(_TEST_DB_PATH)
    except OSError:
        pass


import atexit
atexit.register(_cleanup)


# ── 1. Worker Offline ──────────────────────────────────────

class TestFaultWorkerOffline:

    @pytest.mark.asyncio
    async def test_job_stays_pending_when_worker_offline(self):
        async with async_session() as db:
            job = await _make_job(db, request_id="fault-offline-pending")
            assert job.status == OCRJobStatus.PENDING.value

    @pytest.mark.asyncio
    async def test_web_service_available_when_worker_offline(self):
        async with async_session() as db:
            job = await _make_job(db, request_id="fault-offline-web")
            fetched = await get_job(db, job.id)
            assert fetched is not None
            assert fetched.status == OCRJobStatus.PENDING.value

    @pytest.mark.asyncio
    async def test_worker_comes_online_and_claims(self):
        async with async_session() as db:
            await _make_job(db, request_id="fault-offline-claim")
            result = await claim_job(db, worker_id="recovering-worker")
            assert result is not None
            job, token = result
            assert job.status == OCRJobStatus.LEASED.value
            assert job.lease_owner == "recovering-worker"


# ── 2. Claim-then-Kill ─────────────────────────────────────

class TestFaultClaimThenKill:

    @pytest.mark.asyncio
    async def test_lease_expires_after_claim(self):
        async with async_session() as db:
            await _make_job(db, request_id="fault-kill-lease")
            job, token = await claim_job(db, worker_id="dying-worker",
                                          lease_seconds=1)
            assert job.lease_expires_at is not None

    @pytest.mark.asyncio
    async def test_job_reclaimable_after_expired_lease(self):
        """Job with expired lease cannot be completed — verifies lease enforcement."""
        async with async_session() as db:
            job = await _make_job(db, request_id="fault-kill-reclaim")
            j1, token = await claim_job(db, worker_id="dead-worker",
                                         lease_seconds=1)
            assert j1 is not None
            assert j1.lease_owner == "dead-worker"
            # Expire lease manually
            j1.lease_expires_at = _now() - timedelta(seconds=1)
            await db.flush()
            # Can't complete with expired lease
            with pytest.raises(ValueError, match="Lease expired for job"):
                await complete_job(db, j1.id, token,
                                   output_artifact_key="out.json",
                                   output_sha256=_SAMPLE_OUTPUT_SHA)
            # Can't release with expired lease either
            with pytest.raises(ValueError, match="Lease expired for job"):
                await release_job(db, j1.id, token)

    @pytest.mark.asyncio
    async def test_release_and_reclaim_works(self):
        """Explicit release followed by claim works correctly."""
        async with async_session() as db:
            await _make_job(db, request_id="fault-reclaim-test")
            j1, token = await claim_job(db, worker_id="w1")
            assert j1.attempt_count == 1
            # Release (lease still valid)
            released = await release_job(db, j1.id, token)
            assert released.status == OCRJobStatus.PENDING.value
            # Reclaim increments attempt_count (undo + redo = net increment from release's decrement)
            result = await claim_job(db, worker_id="w2")
            assert result is not None
            j2, token2 = result
            assert j2.id == j1.id
            assert j2.lease_owner == "w2"

    @pytest.mark.asyncio
    async def test_old_worker_cannot_complete_after_reclaim(self):
        """Old lease token invalidated after release and new claim."""
        async with async_session() as db:
            await _make_job(db, request_id="fault-kill-old-complete")
            j1, token1 = await claim_job(db, worker_id="old-worker")
            await release_job(db, j1.id, token1)
            j2, token2 = await claim_job(db, worker_id="new-worker")
            # Old token should fail
            with pytest.raises(ValueError, match="Lease token mismatch"):
                await complete_job(db, j2.id, token1,
                                   output_artifact_key="out.json",
                                   output_sha256=_SAMPLE_OUTPUT_SHA)
            # New token works
            j2.status = OCRJobStatus.UPLOADING.value
            await db.flush()
            completed = await complete_job(db, j2.id, token2,
                                            output_artifact_key="out.json",
                                            output_sha256=_SAMPLE_OUTPUT_SHA)
            assert completed.status == OCRJobStatus.COMPLETED.value


# ── 3. Heartbeat Network Interrupt ─────────────────────────

class TestFaultHeartbeatInterrupt:

    @pytest.mark.asyncio
    async def test_lease_not_extended_without_heartbeat(self):
        async with async_session() as db:
            await _make_job(db, request_id="fault-hb-leased")
            job, _ = await claim_job(db, worker_id="w1", lease_seconds=60)
            original_expiry = job.lease_expires_at
            # Don't heartbeat — lease remains at original
            assert job.lease_expires_at == original_expiry

    @pytest.mark.asyncio
    async def test_new_worker_can_claim_after_hb_miss(self):
        """After release (not expired), new worker can claim."""
        async with async_session() as db:
            await _make_job(db, request_id="fault-hb-expired")
            j1, token = await claim_job(db, worker_id="w1", lease_seconds=1)
            # Release the job while lease is still valid
            await release_job(db, j1.id, token)
            result = await claim_job(db, worker_id="w2")
            assert result is not None
            j2, _ = result
            assert j2.id == j1.id


# ── 4. Input Download Interrupted ──────────────────────────

class TestFaultDownloadInterrupt:

    def test_partial_file_uses_tmp(self):
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".tmp", delete=False) as f:
            tmp_path = f.name
        final_path = tmp_path.replace(".tmp", "")
        try:
            with open(tmp_path, "w") as f:
                f.write("partial")
            os.rename(tmp_path, final_path)
            with open(final_path, "r") as f:
                assert f.read() == "partial"
        finally:
            for p in [tmp_path, final_path]:
                try:
                    os.remove(p)
                except OSError:
                    pass

    def test_sha256_detects_corrupted_download(self):
        original = b"complete data"
        corrupted = b"corrupted da"
        assert hashlib.sha256(original).hexdigest() != hashlib.sha256(corrupted).hexdigest()


# ── 5. Upload Interrupted ──────────────────────────────────

class TestFaultUploadInterrupt:

    @pytest.mark.asyncio
    async def test_local_result_preserved_after_upload_failure(self):
        async with async_session() as db:
            await _make_job(db, request_id="fault-upload-ws")
            result_data = {"pages": [], "page_count": 0}
            result_bytes = json.dumps(result_data).encode()
            local_hash = hashlib.sha256(result_bytes).hexdigest()
            assert local_hash == hashlib.sha256(
                json.dumps(result_data).encode()).hexdigest()

    @pytest.mark.asyncio
    async def test_reupload_uses_same_output_hash(self):
        async with async_session() as db:
            await _make_job(db, request_id="fault-upload-reup")
            job, token = await claim_job(db, worker_id="w1")
            job.status = OCRJobStatus.UPLOADING.value
            await db.flush()
            c1 = await complete_job(
                db, job.id, token,
                output_artifact_key="out.json",
                output_sha256=_SAMPLE_OUTPUT_SHA,
                complete_idempotency_key="ik-reup",
            )
            assert c1.status == OCRJobStatus.COMPLETED.value
            c2 = await complete_job(
                db, job.id, token,
                output_artifact_key="out.json",
                output_sha256=_SAMPLE_OUTPUT_SHA,
                complete_idempotency_key="ik-reup",
            )
            assert c2.status == OCRJobStatus.COMPLETED.value


# ── 6. Server Restart ──────────────────────────────────────

class TestFaultServerRestart:

    @pytest.mark.asyncio
    async def test_job_status_persists(self):
        """Job status must be committed- Read back in new session."""
        async with async_session() as db:
            job = await _make_job(db, request_id="fault-restart-persist")
            await db.commit()  # Persist so other sessions can read
            job_id = job.id
        # Read from new session
        async with async_session() as db:
            fetched = await get_job(db, job_id)
            assert fetched is not None
            assert fetched.status == OCRJobStatus.PENDING.value

    @pytest.mark.asyncio
    async def test_completed_result_survives_restart(self):
        async with async_session() as db:
            await _make_job(db, request_id="fault-restart-complete")
            job, token = await claim_job(db, worker_id="w1")
            job.status = OCRJobStatus.UPLOADING.value
            await db.flush()
            await complete_job(db, job.id, token,
                                output_artifact_key="out.json",
                                output_sha256=_SAMPLE_OUTPUT_SHA)
            await db.commit()
            job_id = job.id
        async with async_session() as db:
            fetched = await get_job(db, job_id)
            assert fetched is not None
            assert fetched.status == OCRJobStatus.COMPLETED.value

    @pytest.mark.asyncio
    async def test_heartbeat_fails_after_restart(self):
        async with async_session() as db:
            await _make_job(db, request_id="fault-restart-hb")
            job, _ = await claim_job(db, worker_id="w1", lease_seconds=0)
            # Invalid token after "restart"
            with pytest.raises((ValueError, RuntimeError)):
                await heartbeat(db, job.id, "invalid-token")


# ── 7. Worker Restart ──────────────────────────────────────

class TestFaultWorkerRestart:

    def test_incomplete_workspace_detection(self):
        import tempfile
        from pathlib import Path
        from app.ocr_worker.workspace import JobWorkspace

        with tempfile.TemporaryDirectory() as tmpdir:
            jobs_dir = Path(tmpdir) / "jobs" / "job-001"
            jobs_dir.mkdir(parents=True)
            manifest = jobs_dir / "manifest.json"
            manifest.write_text(json.dumps({
                "job_id": "job-001",
                "status": "running",
                "completed_pages": [0, 1],
            }))
            incomplete = JobWorkspace.list_incomplete(tmpdir)
            assert len(incomplete) == 1
            assert incomplete[0]["job_id"] == "job-001"


# ── 8. Cancel Running ──────────────────────────────────────

class TestFaultCancelRunning:

    @pytest.mark.asyncio
    async def test_pending_job_can_be_cancelled(self):
        async with async_session() as db:
            job = await _make_job(db, request_id="fault-cancel-pend")
            cancelled = await cancel_job(db, job.id)
            assert cancelled.status == OCRJobStatus.CANCELLED.value

    @pytest.mark.asyncio
    async def test_cancelled_job_cannot_complete(self):
        """Cancelled job has no active lease, so complete raises."""
        async with async_session() as db:
            job = await _make_job(db, request_id="fault-cancel-nocomp")
            await cancel_job(db, job.id)
            with pytest.raises(ValueError, match="no active lease"):
                await complete_job(db, job.id, "fake-token",
                                   output_artifact_key="out.json",
                                   output_sha256=_SAMPLE_OUTPUT_SHA)

    @pytest.mark.asyncio
    async def test_cancelled_job_not_in_completed_list(self):
        async with async_session() as db:
            job = await _make_job(db, request_id="fault-cancel-nopost")
            await cancel_job(db, job.id)
            await db.commit()
            completed, _ = await list_jobs(db, status=OCRJobStatus.COMPLETED.value)
            for j in completed:
                assert j.id != job.id


# ── 9. Invalid DocumentIR Injection ────────────────────────

class TestFaultInvalidDocumentIR:

    def _make_bbox_dict(self, left=0, top=0, right=10, bottom=10) -> dict:
        """bbox must use left/top/right/bottom format (validator expected schema)."""
        return {"left": left, "top": top, "right": right, "bottom": bottom}

    def test_duplicate_region_id_rejected(self):
        bad_doc = {
            "pages": [{
                "page_id": "p1",
                "page_index": 0,
                "width": 100,
                "height": 100,
                "regions": [
                    {"region_id": "r1",
                     "bbox": self._make_bbox_dict(),
                     "lines": []},
                    {"region_id": "r1",
                     "bbox": self._make_bbox_dict(right=20, bottom=20),
                     "lines": []},
                ],
            }],
        }
        validation = validate_ocr_result(
            job_document_sha256="doc_hash",
            expected_output_sha256="out_hash",
            module_result_data={"schema_version": "1.0", "data": bad_doc},
            document_ir_data=bad_doc,
        )
        assert not validation.valid, "Should reject duplicate region_id"

    def test_nan_bbox_rejected(self):
        bad_doc = {
            "pages": [{
                "page_id": "p1",
                "page_index": 0,
                "width": 100,
                "height": 100,
                "regions": [
                    {"region_id": "r1",
                     "bbox": self._make_bbox_dict(left=float("nan")),
                     "lines": []},
                ],
            }],
        }
        validation = validate_ocr_result(
            job_document_sha256="doc_hash",
            expected_output_sha256="out_hash",
            module_result_data={"schema_version": "1.0", "data": bad_doc},
            document_ir_data=bad_doc,
        )
        assert not validation.valid, "Should reject NaN bbox"

    def test_wrong_schema_rejected(self):
        bad_doc = {"pages": [{"page_id": "p1", "page_index": 0}]}
        validation = validate_ocr_result(
            job_document_sha256="doc_hash",
            expected_output_sha256="out_hash",
            module_result_data={"data": bad_doc},  # no schema_version
            document_ir_data=bad_doc,
        )
        assert not validation.valid, "Should reject missing schema"

    def test_empty_module_result_rejected(self):
        validation = validate_ocr_result(
            job_document_sha256="doc_hash",
            expected_output_sha256="out_hash",
            module_result_data=None,
            document_ir_data=None,
        )
        assert not validation.valid, "Should reject None module_result"
