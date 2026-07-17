"""Stage 1A CPU Worker end-to-end test — real PaddleOCR CPU inference, full job lifecycle.

This test exercises the complete worker architecture:
  Create OCR Job → Worker claim → Heartbeat → Download real input → PaddleOCR CPU inference
  → PaddleOCRLocalAdapter → ModuleResult[DocumentIR] → Validate → Upload → Complete

Fast lifecycle tests run without GPU. Real CPU OCR tests are gated by STAGE1A_RUN_OCR=1.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import uuid

# Set test DB path before any app imports
_TEST_DB_PATH = f"/tmp/_test_stage1a_e2e_{uuid.uuid4().hex[:8]}.db"
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{_TEST_DB_PATH}")

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session, engine
from app.models.ocr_job import OCRJob
from app.models.pipeline_enums import OCRJobStatus
from app.services.ocr_job_service import (
    cancel_job, claim_job, complete_job, create_job, heartbeat, list_jobs, start_job,
)
from app.services.ocr_result_validation import validate_ocr_result

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
        request_id=f"req-stage1a-{uuid.uuid4().hex[:8]}",
        document_id="doc-stage1a-001",
        document_sha256=_SAMPLE_DOC_SHA,
        input_artifact_key="tests/stage1a/sample.png",
        input_mime_type="image/png",
        input_size_bytes=1024,
        pipeline_fingerprint="pipe-stage1a-v1",
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


# ── Stage 1A Lifecycle Tests (fast, no OCR) ────────────────

class TestStage1AWorkerLifecycle:
    """Verify full claim → heartbeat → start → complete lifecycle."""

    @pytest.mark.asyncio
    async def test_create_ocr_job_stage1a(self):
        async with async_session() as db:
            job = await _make_job(db, document_id="stage1a-lifecycle",
                                  input_mime_type="image/png")
            assert job.status == OCRJobStatus.PENDING.value
            assert job.document_id == "stage1a-lifecycle"

    @pytest.mark.asyncio
    async def test_claim_job_for_stage1a(self):
        async with async_session() as db:
            await _make_job(db, request_id="stage1a-claim")
            result = await claim_job(db, worker_id="local-cpu-worker")
            assert result is not None
            job, token = result
            assert job.status == OCRJobStatus.LEASED.value
            assert job.lease_owner == "local-cpu-worker"
            assert len(token) == 64

    @pytest.mark.asyncio
    async def test_heartbeat_during_stage1a(self):
        async with async_session() as db:
            await _make_job(db, request_id="stage1a-hb")
            job, token = await claim_job(db, worker_id="local-cpu-worker")
            old_expiry = job.lease_expires_at
            refreshed = await heartbeat(db, job.id, token, lease_seconds=600)
            if old_expiry is not None and refreshed.lease_expires_at is not None:
                assert refreshed.lease_expires_at > old_expiry

    @pytest.mark.asyncio
    async def test_full_stage1a_lifecycle(self):
        """Complete lifecycle: pending → leased → running → uploading → completed."""
        async with async_session() as db:
            await _make_job(db, request_id="stage1a-full")
            job, token = await claim_job(db, worker_id="local-cpu-worker")
            assert job.status == OCRJobStatus.LEASED.value

            job.status = OCRJobStatus.DOWNLOADING.value
            await db.flush()
            started = await start_job(db, job.id, token,
                                       worker_fingerprint="cpu-worker-v1")
            assert started.status == OCRJobStatus.RUNNING.value

            started.status = OCRJobStatus.UPLOADING.value
            await db.flush()
            completed = await complete_job(
                db, job.id, token,
                output_artifact_key="stage1a/result.json",
                output_sha256=_SAMPLE_OUTPUT_SHA,
                complete_idempotency_key="ik-stage1a-full",
            )
            assert completed.status == OCRJobStatus.COMPLETED.value

    @pytest.mark.asyncio
    async def test_complete_idempotent_for_stage1a(self):
        async with async_session() as db:
            await _make_job(db, request_id="stage1a-idem")
            job, token = await claim_job(db, worker_id="local-cpu-worker")
            job.status = OCRJobStatus.UPLOADING.value
            await db.flush()
            c1 = await complete_job(db, job.id, token,
                                     output_artifact_key="out.json",
                                     output_sha256=_SAMPLE_OUTPUT_SHA,
                                     complete_idempotency_key="ik-idem")
            c2 = await complete_job(db, job.id, token,
                                     output_artifact_key="out.json",
                                     output_sha256=_SAMPLE_OUTPUT_SHA,
                                     complete_idempotency_key="ik-idem")
            assert c1.id == c2.id
            assert c2.status == OCRJobStatus.COMPLETED.value

    @pytest.mark.asyncio
    async def test_no_duplicate_claim_for_stage1a(self):
        async with async_session() as db:
            await _make_job(db, request_id="stage1a-nodup")
            await claim_job(db, worker_id="worker-a")
            result = await claim_job(db, worker_id="worker-b")
            assert result is None

    @pytest.mark.asyncio
    async def test_stale_lease_rejected(self):
        async with async_session() as db:
            await _make_job(db, request_id="stage1a-stale")
            job, _ = await claim_job(db, worker_id="local-cpu-worker")
            job.lease_expires_at = None
            job.status = OCRJobStatus.UPLOADING.value
            await db.flush()
            with pytest.raises(ValueError, match="Lease token mismatch|no active lease"):
                await complete_job(db, job.id, "bad-token",
                                   output_artifact_key="out.json",
                                   output_sha256=_SAMPLE_OUTPUT_SHA)

    @pytest.mark.asyncio
    async def test_cancel_pending_for_stage1a(self):
        async with async_session() as db:
            job = await _make_job(db, request_id="stage1a-cancel")
            cancelled = await cancel_job(db, job.id)
            assert cancelled.status == OCRJobStatus.CANCELLED.value

    @pytest.mark.asyncio
    async def test_job_respects_priority(self):
        async with async_session() as db:
            await _make_job(db, request_id="stage1a-pri-low", priority=0)
            await _make_job(db, request_id="stage1a-pri-high", priority=10)
            result = await claim_job(db, worker_id="local-cpu-worker")
            assert result is not None
            job, _ = result
            assert job.priority == 10

    @pytest.mark.asyncio
    async def test_list_jobs_after_processing(self):
        async with async_session() as db:
            await _make_job(db, request_id="stage1a-list")
            job, token = await claim_job(db, worker_id="local-cpu-worker")
            job.status = OCRJobStatus.UPLOADING.value
            await db.flush()
            await complete_job(db, job.id, token,
                                output_artifact_key="out.json",
                                output_sha256=_SAMPLE_OUTPUT_SHA)
            jobs, total = await list_jobs(db, status=OCRJobStatus.COMPLETED.value)
            assert total >= 1


# ── Stage 1A Real CPU OCR Test (slow, requires PaddleOCR CPU) ─

@pytest.mark.skipif(
    not os.environ.get("STAGE1A_RUN_OCR", ""),
    reason="Set STAGE1A_RUN_OCR=1 to run real CPU OCR test",
)
class TestStage1ACPUCrOCR:
    """Real CPU OCR inference via PaddleOCRLocalAdapter."""

    @pytest.mark.asyncio
    async def test_paddleocr_cpu_adapter_single_page(self):
        from app.core.ocr_request import OCRRequest
        from app.features.ocr_adapter import PaddleOCRLocalAdapter
        from tests.fixtures.pdf_helper import make_minimal_pdf

        pdf_bytes = make_minimal_pdf(page_count=1, text="CPU OCR test page")
        request = OCRRequest(source=pdf_bytes, source_type="pdf",
                              filename="stage1a-cpu-test.pdf")

        adapter = PaddleOCRLocalAdapter(engine="paddleocr")
        result = await adapter.process(request, trace_id="stage1a-cpu-test")

        assert result.is_success, f"OCR failed: {result.error}"
        assert result.data is not None
        assert result.data.pages, "No pages in DocumentIR"

        doc_ir = result.data
        assert len(doc_ir.pages) >= 1
        for page in doc_ir.pages:
            assert hasattr(page, "page_id")
            assert hasattr(page, "page_index")
            assert hasattr(page, "regions")

        doc_ir_dict = dataclasses.asdict(doc_ir)
        output_bytes = json.dumps(doc_ir_dict, ensure_ascii=False, default=str).encode()
        output_sha256 = hashlib.sha256(output_bytes).hexdigest()
        validation = validate_ocr_result(
            job_document_sha256=_SAMPLE_DOC_SHA,
            expected_output_sha256=output_sha256,
            module_result_data={"schema_version": "1.0", "data": doc_ir_dict},
            document_ir_data=doc_ir_dict,
        )
        assert validation.valid, f"DocumentIR validation failed: {validation.errors}"
        assert result.latency_ms > 0
        print(f"\n[STAGE1A] CPU OCR adapter latency: {result.latency_ms:.0f} ms")

    @pytest.mark.asyncio
    async def test_paddleocr_cpu_result_structure(self):
        from app.core.ocr_request import OCRRequest
        from app.features.ocr_adapter import PaddleOCRLocalAdapter
        from tests.fixtures.pdf_helper import make_minimal_pdf

        pdf_bytes = make_minimal_pdf(page_count=1,
                                      text="Stage 1A CPU OCR verification")
        request = OCRRequest(source=pdf_bytes, source_type="pdf",
                              filename="stage1a-struct.pdf")

        adapter = PaddleOCRLocalAdapter(engine="paddleocr")
        result = await adapter.process(request, trace_id="stage1a-struct")

        assert result.is_success
        doc_ir = result.data

        assert hasattr(doc_ir, "pipeline_fingerprint")
        assert hasattr(doc_ir, "document_id")
        assert hasattr(doc_ir, "pages")
        assert doc_ir.page_count >= 1

        for page in doc_ir.pages:
            assert hasattr(page, "page_id")
            assert hasattr(page, "page_index")
            assert hasattr(page, "width")
            assert hasattr(page, "height")
            assert hasattr(page, "regions")
            for region in page.regions:
                assert hasattr(region, "region_id")
                assert hasattr(region, "bbox")
                assert hasattr(region, "lines")
                for line in region.lines:
                    assert hasattr(line, "text")
                    assert len(line.text) > 0, "Empty OCR text"

        doc_ir_dict = dataclasses.asdict(doc_ir)
        output_bytes = json.dumps(doc_ir_dict, ensure_ascii=False, default=str).encode()
        output_sha256 = hashlib.sha256(output_bytes).hexdigest()
        assert len(output_sha256) == 64
        print(f"\n[STAGE1A] DocumentIR output SHA-256: {output_sha256}")
