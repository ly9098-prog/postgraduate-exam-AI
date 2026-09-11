"""Regression tests for batch image import DB optimizations.

Covers:
1. request_id idempotency fix (_find_job_by_request_id)
2. Trace event ordering by id (not seq/FOR UPDATE)
3. poll_job_summary SQL aggregation correctness
4. API OCR model config caching (resolve_active_model called once)
5. submit_to_review batch flush (no per-item flush)
6. Batch merge bulk update (no N+1 db.get)
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import UTC
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base


async def _make_session(tmp_path: Path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'batch_opt_test.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False), engine


def _run(coro):
    return asyncio.run(coro)


def _now():
    from datetime import datetime
    return datetime.now(UTC).replace(tzinfo=None)


@pytest.fixture(autouse=True)
def patch_async_session(tmp_path):
    """Patch global async_session for batch service tests."""
    import app.features.batch_image_import_service as svc
    from app.core import database

    sm, _engine = _run(_make_session(tmp_path))

    original = database.async_session
    database.async_session = sm
    svc.async_session = sm

    yield

    database.async_session = original
    svc.async_session = original


def _make_job(job_id: str, **overrides) -> dict:
    now = _now()
    d = {
        "job_id": job_id,
        "source_type": "image",
        "total": 2,
        "concurrency": 1,
        "status": "queued",
        "next_event_seq": 1,
        "started_at": now,
        "queued_at": now,
        "updated_at": now,
    }
    d.update(overrides)
    return d


def _make_item(job_id: str, seq: int = 1, **overrides) -> dict:
    now = _now()
    d = {
        "job_id": job_id,
        "seq": seq,
        "source_file": f"img_{seq}.png",
        "status": "pending",
        "created_at": now,
        "updated_at": now,
    }
    d.update(overrides)
    return d


# =========================================================================
# 1. request_id idempotency
# =========================================================================


class TestRequestIdIdempotency:
    """_find_job_by_request_id must correctly find existing job by item.request_id."""

    def test_find_job_by_request_id_returns_existing(self, tmp_path):
        """Given job with request_id, _find_job_by_request_id returns the job_id."""
        from app.features.batch_image_import_service import _find_job_by_request_id
        from app.models.import_batch_job import ImportBatchJob, ImportBatchJobItem

        async def _go():
            sm, _ = await _make_session(tmp_path)
            async with sm() as db:
                # request_id must be on the job itself for _find_job_by_request_id
                db.add(ImportBatchJob(**_make_job("job_req_001", request_id="req_abc")))
                db.add(ImportBatchJobItem(
                    **_make_item("job_req_001", seq=1, request_id="req_abc"),
                ))
                db.add(ImportBatchJobItem(
                    **_make_item("job_req_001", seq=2, request_id="req_abc"),
                ))
                await db.commit()

            async with sm() as db:
                result = await _find_job_by_request_id(db, "req_abc")
            assert result == "job_req_001"

        _run(_go())

    def test_find_job_by_request_id_returns_none_for_unknown(self, tmp_path):
        """Unknown request_id returns None."""
        from app.features.batch_image_import_service import _find_job_by_request_id

        async def _go():
            sm, _ = await _make_session(tmp_path)
            async with sm() as db:
                result = await _find_job_by_request_id(db, "nonexistent")
            assert result is None

        _run(_go())

    def test_find_job_by_request_id_empty_returns_none(self, tmp_path):
        """Empty request_id returns None immediately."""
        from app.features.batch_image_import_service import _find_job_by_request_id

        async def _go():
            sm, _ = await _make_session(tmp_path)
            async with sm() as db:
                result = await _find_job_by_request_id(db, "")
            assert result is None

        _run(_go())

    def test_duplicate_request_id_returns_existing_job(self, tmp_path):
        """create_batch_job with duplicate request_id returns existing stub."""
        from app.features.batch_image_import_service import (
            BatchImageSource,
            create_batch_job,
        )
        from app.models.import_batch_job import ImportBatchJob

        async def _go():
            sm, _ = await _make_session(tmp_path)
            sources = [BatchImageSource(seq=1, source_file="test.png", temp_path="/tmp/test.png")]

            async with sm() as db:
                # First creation
                job1 = await create_batch_job(
                    db, job_id="BIMG_IDEM_001", sources=sources,
                    subject="math2", concurrency=2, created_by="admin:1",
                    request_id="req_idem_001",
                )
                assert job1.job_id == "BIMG_IDEM_001"
                assert job1.status == "queued"
                await db.commit()

            async with sm() as db:
                # Second creation with same request_id
                sources2 = [BatchImageSource(seq=1, source_file="test.png", temp_path="/tmp/test2.png")]
                job2 = await create_batch_job(
                    db, job_id="BIMG_IDEM_002", sources=sources2,
                    subject="math2", concurrency=2, created_by="admin:1",
                    request_id="req_idem_001",
                )
                # Should return stub pointing to existing job
                assert job2.job_id == "BIMG_IDEM_001"
                assert job2.status == "duplicate"

            # Verify only one job was actually created
            async with sm() as db:
                count = await db.scalar(select(func.count(ImportBatchJob.job_id)))
                assert count == 1, "Duplicate request_id should not create new job"

        _run(_go())


# =========================================================================
# 2. Trace event ordering by id (not seq)
# =========================================================================


class TestTraceEventOrdering:
    """Trace events should be ordered by auto-increment id, not seq."""

    def test_poll_trace_events_returns_by_id_order(self, tmp_path):
        """poll_trace_events returns events ordered by auto-increment id."""
        from app.features.batch_image_import_service import poll_trace_events
        from app.models.import_batch_job import BatchJobTraceEvent

        async def _go():
            sm, _ = await _make_session(tmp_path)
            job_id = "trace_order_001"
            async with sm() as db:
                # Insert events — ordering should be by auto-increment id
                for seq_val in [10, 5, 15]:
                    db.add(BatchJobTraceEvent(
                        job_id=job_id, seq=seq_val,
                        step="test", status="success",
                        message=f"seq={seq_val}",
                    ))
                await db.commit()

            async with sm() as db:
                events = await poll_trace_events(db, job_id)
            assert len(events) == 3
            # "seq" in response = auto-increment id (1, 2, 3)
            assert events[0]["seq"] == 1  # First inserted row
            assert events[1]["seq"] == 2  # Second inserted row
            assert events[2]["seq"] == 3  # Third inserted row

        _run(_go())

    def test_poll_trace_events_since_id(self, tmp_path):
        """poll_trace_events with since_id returns only events after that id."""
        from app.features.batch_image_import_service import poll_trace_events
        from app.models.import_batch_job import BatchJobTraceEvent

        async def _go():
            sm, _ = await _make_session(tmp_path)
            job_id = "trace_since_001"
            async with sm() as db:
                for i in range(1, 6):
                    db.add(BatchJobTraceEvent(
                        job_id=job_id, seq=i,
                        step="test", status="success",
                        message=f"event_{i}",
                    ))
                await db.commit()

            async with sm() as db:
                # since_id=2 → should get events with id > 2 (i.e., events with ids 3,4,5)
                events = await poll_trace_events(db, job_id, since_id=2)
            assert len(events) == 3
            assert events[0]["seq"] == 3  # id 3 → third insertion

        _run(_go())


# =========================================================================
# 3. poll_job_summary SQL aggregation
# =========================================================================


class TestPollJobSummaryAggregation:
    """poll_job_summary should use SQL GROUP BY for counts."""

    def test_summary_counts_aggregated(self, tmp_path):
        """Item counts come from SQL aggregation, not Python loop over all items."""
        from app.features.batch_image_import_service import poll_job_summary
        from app.models.import_batch_job import ImportBatchJob, ImportBatchJobItem

        async def _go():
            sm, _ = await _make_session(tmp_path)
            job_id = "summary_agg_001"
            async with sm() as db:
                db.add(ImportBatchJob(**_make_job(job_id, status="running")))
                db.add(ImportBatchJobItem(**_make_item(job_id, 1, status="succeeded", question_count=3)))
                db.add(ImportBatchJobItem(**_make_item(job_id, 2, status="succeeded", question_count=2)))
                db.add(ImportBatchJobItem(**_make_item(job_id, 3, status="failed", question_count=0)))
                db.add(ImportBatchJobItem(**_make_item(job_id, 4, status="pending", question_count=0)))
                await db.commit()

            async with sm() as db:
                summary = await poll_job_summary(db, job_id)

            assert summary is not None
            assert summary["succeeded"] == 2
            assert summary["failed"] == 1
            assert summary["total_questions"] == 5
            assert summary["status"] == "running"

        _run(_go())

    def test_summary_all_failed(self, tmp_path):
        from app.features.batch_image_import_service import poll_job_summary
        from app.models.import_batch_job import ImportBatchJob, ImportBatchJobItem

        async def _go():
            sm, _ = await _make_session(tmp_path)
            job_id = "summary_all_fail"
            async with sm() as db:
                db.add(ImportBatchJob(**_make_job(job_id, status="failed")))
                for i in range(3):
                    db.add(ImportBatchJobItem(**_make_item(job_id, i, status="failed")))
                await db.commit()

            async with sm() as db:
                summary = await poll_job_summary(db, job_id)

            assert summary is not None
            assert summary["succeeded"] == 0
            assert summary["failed"] == 3
            assert summary["status"] == "failed"

        _run(_go())

    def test_summary_empty_job(self, tmp_path):
        from app.features.batch_image_import_service import poll_job_summary
        from app.models.import_batch_job import ImportBatchJob

        async def _go():
            sm, _ = await _make_session(tmp_path)
            async with sm() as db:
                db.add(ImportBatchJob(**_make_job("empty_summary", status="queued")))
                await db.commit()

            async with sm() as db:
                summary = await poll_job_summary(db, "empty_summary")

            assert summary is not None
            assert summary["succeeded"] == 0
            assert summary["failed"] == 0
            assert summary["total_questions"] == 0

        _run(_go())


# =========================================================================
# 4. API OCR model config caching
# =========================================================================


class TestApiOcrModelConfigCaching:
    """API OCR mode should resolve model config once for all images."""

    def test_api_mode_resolves_config_once(self, tmp_path):
        """run_batch_job with api mode calls resolve_active_model exactly once."""
        from app.features.batch_image_import_service import (
            BatchImageSource,
            run_batch_job,
        )
        from app.models.import_batch_job import ImportBatchJob, ImportBatchJobItem

        async def _go():
            sm, _ = await _make_session(tmp_path)

            # Seed job + items
            job_id = "api_cfg_cache_001"
            async with sm() as db:
                db.add(ImportBatchJob(**_make_job(job_id)))
                db.add(ImportBatchJobItem(**_make_item(job_id, 1, image_import_id="img_1")))
                db.add(ImportBatchJobItem(**_make_item(job_id, 2, image_import_id="img_2")))
                await db.commit()

            resolved = MagicMock(
                endpoint="https://test.api",
                model_name="test-model",
                timeout_seconds=120,
                max_retries=3,
            )
            resolver = MagicMock()
            resolver.resolve_for_capability = AsyncMock(return_value=resolved)
            resolver.resolve_secret = AsyncMock(return_value="test_key")

            # Create temp files that actually exist
            tmp1 = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            tmp1.write(b"fake_image_data")
            tmp1.close()
            tmp2 = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            tmp2.write(b"fake_image_data_2")
            tmp2.close()

            sources = [
                BatchImageSource(seq=1, source_file="img1.png", temp_path=tmp1.name),
                BatchImageSource(seq=2, source_file="img2.png", temp_path=tmp2.name),
            ]

            try:
                with patch(
                    "app.services.model_config_resolver.AIModelConfigResolver",
                    return_value=resolver,
                ), patch(
                    "app.features.batch_image_import_service._run_single_image",
                    return_value={
                        "batch_id": None,
                        "status": "failed",
                        "errors": ["test mock - not really processing"],
                        "stats": {"to_review": 0},
                    },
                ):
                    await run_batch_job(
                        job_id=job_id, sources=sources,
                        subject="math2", options={"ocr_mode": "api"},
                        concurrency=1,
                    )
            finally:
                try:
                    os.unlink(tmp1.name)
                except OSError:
                    pass
                try:
                    os.unlink(tmp2.name)
                except OSError:
                    pass

            resolver.resolve_for_capability.assert_awaited_once()
            resolver.resolve_secret.assert_awaited_once_with(resolved)

        _run(_go())

    def test_local_mode_does_not_resolve_api_config(self, tmp_path):
        """local OCR mode should NOT call resolve_active_model for OCR config."""
        from app.features.batch_image_import_service import (
            BatchImageSource,
            run_batch_job,
        )
        from app.models.import_batch_job import ImportBatchJob, ImportBatchJobItem

        async def _go():
            sm, _ = await _make_session(tmp_path)

            job_id = "local_cfg_001"
            async with sm() as db:
                db.add(ImportBatchJob(**_make_job(job_id)))
                db.add(ImportBatchJobItem(**_make_item(job_id, 1)))
                await db.commit()

            resolve_count = {"count": 0}

            async def _count_resolve(db, **kw):
                resolve_count["count"] += 1
                return {"api_key": "test_key", "api_base_url": "https://test.api", "model_name": "test-model"}

            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            tmp.write(b"fake")
            tmp.close()

            sources = [
                BatchImageSource(seq=1, source_file="img1.png", temp_path=tmp.name),
            ]

            try:
                with patch(
                    "app.services.model_config_resolver.resolve_active_model",
                    side_effect=_count_resolve,
                ), patch(
                    "app.features.batch_image_import_service._run_single_image",
                    return_value={
                        "batch_id": None,
                        "status": "failed",
                        "errors": ["test mock"],
                        "stats": {"to_review": 0},
                    },
                ):
                    await run_batch_job(
                        job_id=job_id, sources=sources,
                        subject="math2", options={"ocr_mode": "local"},
                        concurrency=1,
                    )
            finally:
                try:
                    os.unlink(tmp.name)
                except OSError:
                    pass

            # Should NOT call resolve_active_model for local mode
            assert resolve_count["count"] == 0, (
                f"Expected 0 resolve_active_model calls for local mode, got {resolve_count['count']}"
            )

        _run(_go())


# =========================================================================
# 5. submit_to_review batch flush (no per-item flush)
# =========================================================================


class TestSubmitToReviewBatchFlush:
    """submit_to_review should not flush per-item."""

    def test_batch_flush_no_per_item_flush(self):
        """With batch size=50, only 1 flush per 50 items, not 1 per item."""
        from app.features.review_service import submit_to_review

        db = MagicMock()
        db.add = MagicMock()
        db.add_all = MagicMock()
        db.flush = AsyncMock()
        db.commit = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=None),
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))),
        ))
        db.expunge = MagicMock()
        db.rollback = AsyncMock()

        # Build 120 questions (2 full batches + tail)
        qs = []
        for i in range(120):
            qs.append({
                "stem": f"Question {i} stem text",
                "options": [{"key": "A", "text": "opt_a"}],
                "answer": "A",
                "question_type": "single_choice",
                "subject": "math2",
                "confidence_score": 0.8,
                "is_valid": True,
                "errors": [],
                "warnings": [],
                "stem_hash": f"hash_{i:04d}",
            })

        asyncio.run(submit_to_review(db, qs))

        # Expected: 2 full batch flushes (50 each) + 1 tail flush (20) = 3 flushes total
        # NOT 120 flushes (per-item)
        assert db.flush.call_count == 3, (
            f"Expected 3 flushes (2 batch + 1 tail), got {db.flush.call_count}"
        )
        # 3 commits (2 batch + 1 tail)
        assert db.commit.call_count == 3, (
            f"Expected 3 commits, got {db.commit.call_count}"
        )

    def test_single_item_one_flush(self):
        """Single item → 1 flush only."""
        from app.features.review_service import submit_to_review

        db = MagicMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.commit = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=None),
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))),
        ))
        db.expunge = MagicMock()
        db.rollback = AsyncMock()

        q = [{
            "stem": "Single question",
            "options": [{"key": "A", "text": "opt"}],
            "answer": "A",
            "question_type": "single_choice",
            "subject": "math2",
            "confidence_score": 0.8,
            "is_valid": True,
            "errors": [],
            "warnings": [],
            "stem_hash": "hash_single",
        }]

        asyncio.run(submit_to_review(db, q))

        # Single item: 1 flush (tail) + 1 commit
        assert db.flush.call_count == 1
        assert db.commit.call_count == 1

    def test_returns_ids_after_batch_flush(self):
        """After batch flush, all items have their proper IDs in the response."""
        from app.features.review_service import submit_to_review

        db = MagicMock()
        added = []

        def _add(obj):
            obj.id = len(added) + 1
            added.append(obj)

        db.add = MagicMock(side_effect=_add)
        db.flush = AsyncMock()
        db.commit = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=None),
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))),
        ))
        db.expunge = MagicMock()
        db.rollback = AsyncMock()

        qs = [{"stem": f"Q{i}", "options": [], "answer": "A",
               "question_type": "single_choice", "subject": "math2",
               "confidence_score": 0.8, "is_valid": True, "errors": [],
               "warnings": [], "stem_hash": f"h{i:04d}"} for i in range(60)]

        result = asyncio.run(submit_to_review(db, qs))

        assert result["written"] == 60
        for item in result["items"]:
            assert isinstance(item["id"], int)
            assert item["id"] > 0
        # Check IDs are sequential
        ids = [it["id"] for it in result["items"]]
        assert ids == list(range(1, 61))


# =========================================================================
# 6. Batch merge bulk update
# =========================================================================


class TestBatchMergeBulkUpdate:
    """_batch_merge_commit should use bulk update, not N+1 db.get."""

    def test_bulk_update_items_no_n_plus_1(self, tmp_path):
        """Items are updated via bulk update, not per-item db.get."""
        from app.features.batch_image_import_service import _batch_merge_commit
        from app.models.import_batch_job import ImportBatchJob, ImportBatchJobItem

        async def _go():
            sm, _ = await _make_session(tmp_path)
            job_id = "bulk_merge_001"

            async with sm() as db:
                db.add(ImportBatchJob(**_make_job(job_id)))
                db.add(ImportBatchJobItem(**_make_item(job_id, 1, review_batch_id="OLD_A")))
                db.add(ImportBatchJobItem(**_make_item(job_id, 2, review_batch_id="OLD_B")))
                db.add(ImportBatchJobItem(**_make_item(job_id, 3, review_batch_id="OLD_C")))
                await db.commit()

            async with sm() as db:
                items = (
                    await db.execute(
                        select(ImportBatchJobItem)
                        .where(ImportBatchJobItem.job_id == job_id)
                        .order_by(ImportBatchJobItem.seq)
                    )
                ).scalars().all()

            async with sm() as db:
                async with db.begin():
                    await _batch_merge_commit(
                        db=db, job_id=job_id,
                        merged_batch_id="MERGED",
                        old_batch_ids=["OLD_A", "OLD_B", "OLD_C"],
                        items=items,
                        now=_now(),
                    )

            # Verify all items point to merged batch
            async with sm() as db:
                updated = (
                    await db.execute(
                        select(ImportBatchJobItem)
                        .where(ImportBatchJobItem.job_id == job_id)
                        .order_by(ImportBatchJobItem.seq)
                    )
                ).scalars().all()
            for item in updated:
                assert item.review_batch_id == "MERGED", (
                    f"Item seq={item.seq} should point to MERGED"
                )

        _run(_go())

    def test_supersede_old_batches_no_per_id_loop(self, tmp_path):
        """Old batches are superseded in bulk, not per-batch_id loop."""
        from app.features.batch_image_import_service import _batch_merge_commit
        from app.models.import_batch_job import ImportBatchJob, ImportBatchJobItem
        from app.models.question_import import QuestionImport as QI

        async def _go():
            sm, _ = await _make_session(tmp_path)
            job_id = "bulk_sup_001"

            async with sm() as db:
                db.add(ImportBatchJob(**_make_job(job_id)))
                db.add(ImportBatchJobItem(**_make_item(job_id, 1, review_batch_id="OLD_X")))
                db.add(ImportBatchJobItem(**_make_item(job_id, 2, review_batch_id="OLD_Y")))
                # Seed QI records in old batches
                for bid in ("OLD_X", "OLD_Y"):
                    for i in range(2):
                        db.add(QI(batch_id=bid, source_type="image", raw_data={"q": f"q{i}"}))
                # QI in an unrelated batch should NOT be affected
                db.add(QI(batch_id="UNRELATED", source_type="image", raw_data={"q": "unrelated"}))
                await db.commit()

            async with sm() as db:
                items = (
                    await db.execute(
                        select(ImportBatchJobItem)
                        .where(ImportBatchJobItem.job_id == job_id)
                    )
                ).scalars().all()

            async with sm() as db:
                async with db.begin():
                    count = await _batch_merge_commit(
                        db=db, job_id=job_id,
                        merged_batch_id="MERGED_FINAL",
                        old_batch_ids=["OLD_X", "OLD_Y"],
                        items=items,
                        now=_now(),
                    )
                assert count == 2  # 2 old batches superseded

            # Verify old batch QIs are superseded
            async with sm() as db:
                old_x_qs = (
                    await db.execute(
                        select(QI).where(QI.batch_id == "OLD_X")
                    )
                ).scalars().all()
                for q in old_x_qs:
                    assert q.superseded_by_batch_id == "MERGED_FINAL"

                # Unrelated batch should NOT be affected
                unrelated = (
                    await db.execute(
                        select(QI).where(QI.batch_id == "UNRELATED")
                    )
                ).scalars().all()
                for q in unrelated:
                    assert q.superseded_by_batch_id is None

        _run(_go())


# =========================================================================
# 7. Same-batch duplicate detection in submit_to_review
# =========================================================================


class TestSubmitToReviewSameBatchDuplicates:
    """submit_to_review should detect duplicates within the same flush batch."""

    def test_same_batch_duplicate_detected(self):
        """Two questions with same hash in same flush batch → second marked duplicate."""
        from app.features.review_service import submit_to_review

        db = MagicMock()
        added = []
        def _add(obj):
            obj.id = len(added) + 1
            added.append(obj)

        db.add = MagicMock(side_effect=_add)
        db.flush = AsyncMock()
        db.commit = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=None),
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))),
        ))
        db.expunge = MagicMock()
        db.rollback = AsyncMock()

        # Two questions with identical content → same question_hash
        qs = [
            {
                "stem": "What is 1+1?",
                "options": [{"key": "A", "text": "1"}, {"key": "B", "text": "2"}],
                "answer": "B",
                "question_type": "single_choice",
                "subject": "math2",
                "confidence_score": 0.9,
                "is_valid": True,
                "errors": [],
                "warnings": [],
                "stem_hash": "hash_dup_000",
            },
            {
                "stem": "What is 1+1?",
                "options": [{"key": "A", "text": "1"}, {"key": "B", "text": "2"}],
                "answer": "B",
                "question_type": "single_choice",
                "subject": "math2",
                "confidence_score": 0.9,
                "is_valid": True,
                "errors": [],
                "warnings": [],
                "stem_hash": "hash_dup_000",
            },
        ]

        result = asyncio.run(submit_to_review(db, qs))

        assert result["written"] == 2
        items = result["items"]
        # First item should be normal
        assert items[0]["duplicate_status"] == "normal"
        assert items[0]["duplicate_of_import_id"] is None
        # Second item should be duplicate of first
        assert items[1]["duplicate_status"] == "possible_duplicate"
        assert items[1]["duplicate_of_import_id"] == items[0]["id"], (
            f"Second item should point to first item's id ({items[0]['id']}), "
            f"got {items[1]['duplicate_of_import_id']}"
        )

    def test_cross_batch_duplicate_detected(self):
        """Questions with same hash across flush batches → second batch marked duplicate."""
        from app.features.review_service import (
            _REVIEW_COMMIT_BATCH_SIZE,
            submit_to_review,
        )

        db = MagicMock()
        added = []
        def _add(obj):
            obj.id = len(added) + 1
            added.append(obj)

        db.add = MagicMock(side_effect=_add)
        db.flush = AsyncMock()
        db.commit = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=None),
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))),
        ))
        db.expunge = MagicMock()
        db.rollback = AsyncMock()

        # Create exactly _REVIEW_COMMIT_BATCH_SIZE unique questions + 1 duplicate of the first
        qs = []
        for i in range(_REVIEW_COMMIT_BATCH_SIZE):
            qs.append({
                "stem": f"Unique question {i}",
                "options": [{"key": "A", "text": "opt"}],
                "answer": "A",
                "question_type": "single_choice",
                "subject": "math2",
                "confidence_score": 0.8,
                "is_valid": True,
                "errors": [],
                "warnings": [],
                "stem_hash": f"hash_unique_{i:04d}",
            })
        # Add a duplicate of the first question (different flush batch)
        qs.append({
            "stem": "Unique question 0",
            "options": [{"key": "A", "text": "opt"}],
            "answer": "A",
            "question_type": "single_choice",
            "subject": "math2",
            "confidence_score": 0.8,
            "is_valid": True,
            "errors": [],
            "warnings": [],
            "stem_hash": "hash_unique_0000",
        })

        result = asyncio.run(submit_to_review(db, qs))

        assert result["written"] == _REVIEW_COMMIT_BATCH_SIZE + 1
        items = result["items"]
        # First item should be normal
        assert items[0]["duplicate_status"] == "normal"
        # Last item (duplicate) should point to first
        last = items[-1]
        assert last["duplicate_status"] == "possible_duplicate"
        assert last["duplicate_of_import_id"] == items[0]["id"]

    def test_duplicate_batch_flush_still_batched(self):
        """Same-batch duplicate detection does not degrade flush batching."""
        from app.features.review_service import submit_to_review

        db = MagicMock()
        added = []
        def _add(obj):
            obj.id = len(added) + 1
            added.append(obj)

        db.add = MagicMock(side_effect=_add)
        db.flush = AsyncMock()
        db.commit = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=None),
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))),
        ))
        db.expunge = MagicMock()
        db.rollback = AsyncMock()

        # 100 items with 50 duplicates → still only 3 flushes (2 batch + 1 tail)
        qs = []
        for i in range(100):
            qs.append({
                "stem": f"Question {i % 50}",
                "options": [{"key": "A", "text": "opt"}],
                "answer": "A",
                "question_type": "single_choice",
                "subject": "math2",
                "confidence_score": 0.8,
                "is_valid": True,
                "errors": [],
                "warnings": [],
                "stem_hash": f"hash_{i % 50:04d}",
            })

        db.flush.reset_mock()
        db.commit.reset_mock()
        asyncio.run(submit_to_review(db, qs))

        # 100 items: 2 full batch flushes (50 each) + 0 tail = 2 flushes
        assert db.flush.call_count == 2, (
            f"Expected 2 flushes, got {db.flush.call_count}"
        )


# =========================================================================
# 8. Temp file cleanup on duplicate request_id
# =========================================================================


class TestTempFileCleanupOnDuplicate:
    """Temp files should be cleaned up when request_id is a duplicate."""

    def test_cleanup_temp_sources_removes_files(self, tmp_path):
        """_cleanup_temp_sources should delete existing temp files."""
        from app.api.v1.admin_imports import _cleanup_temp_sources

        # Create actual temp files
        tf1 = tempfile.NamedTemporaryFile(prefix="batch_img_", suffix=".png", delete=False)
        tf1_path = tf1.name
        tf1.close()

        tf2 = tempfile.NamedTemporaryFile(prefix="batch_img_", suffix=".jpg", delete=False)
        tf2_path = tf2.name
        tf2.close()

        assert os.path.exists(tf1_path)
        assert os.path.exists(tf2_path)

        class FakeSource:
            def __init__(self, path):
                self.temp_path = path

        sources = [FakeSource(tf1_path), FakeSource(tf2_path)]
        _cleanup_temp_sources(sources)

        assert not os.path.exists(tf1_path), f"Temp file {tf1_path} should be deleted"
        assert not os.path.exists(tf2_path), f"Temp file {tf2_path} should be deleted"

    def test_cleanup_temp_sources_missing_file_does_not_raise(self, tmp_path):
        """_cleanup_temp_sources should not raise if file is already gone."""
        from app.api.v1.admin_imports import _cleanup_temp_sources

        class FakeSource:
            def __init__(self, path):
                self.temp_path = path

        sources = [FakeSource("/tmp/nonexistent_file_xyz.png")]
        # Should not raise
        _cleanup_temp_sources(sources)

    def test_cleanup_temp_sources_no_temp_path_does_not_raise(self):
        """_cleanup_temp_sources should handle source without temp_path."""
        from app.api.v1.admin_imports import _cleanup_temp_sources

        class FakeSourceNoPath:
            pass

        sources = [FakeSourceNoPath()]
        _cleanup_temp_sources(sources)


# =========================================================================
# 9. Trace event id/seq compatibility
# =========================================================================


class TestTraceEventIdSeqCompat:
    """Trace event API responses must include both id and seq (seq == id)."""

    def test_poll_trace_events_returns_id_and_seq(self, tmp_path):
        """poll_trace_events returns both id and seq, with seq == id."""
        from app.features.batch_image_import_service import poll_trace_events
        from app.models.import_batch_job import BatchJobTraceEvent

        async def _go():
            sm, _ = await _make_session(tmp_path)
            job_id = "id_seq_001"
            async with sm() as db:
                db.add(BatchJobTraceEvent(
                    job_id=job_id, seq=0,
                    step="test", status="success", message="ev1",
                ))
                db.add(BatchJobTraceEvent(
                    job_id=job_id, seq=0,
                    step="test", status="success", message="ev2",
                ))
                await db.commit()

            async with sm() as db:
                events = await poll_trace_events(db, job_id)

            assert len(events) == 2
            for ev in events:
                assert "id" in ev, f"Event missing 'id' field: {ev}"
                assert "seq" in ev, f"Event missing 'seq' field: {ev}"
                assert ev["id"] == ev["seq"], (
                    f"id ({ev['id']}) should equal seq ({ev['seq']})"
                )
            # Events ordered by auto-increment id
            assert events[0]["id"] == 1
            assert events[1]["id"] == 2

        _run(_go())

    def test_poll_trace_events_since_id_not_seq(self, tmp_path):
        """Incremental query uses id, not DB seq. Even with seq=0, since_id works."""
        from app.features.batch_image_import_service import poll_trace_events
        from app.models.import_batch_job import BatchJobTraceEvent

        async def _go():
            sm, _ = await _make_session(tmp_path)
            job_id = "id_seq_since"
            async with sm() as db:
                db.add(BatchJobTraceEvent(
                    job_id=job_id, seq=0,
                    step="test", status="success", message="ev1",
                ))
                db.add(BatchJobTraceEvent(
                    job_id=job_id, seq=0,
                    step="test", status="success", message="ev2",
                ))
                db.add(BatchJobTraceEvent(
                    job_id=job_id, seq=0,
                    step="test", status="success", message="ev3",
                ))
                await db.commit()

            async with sm() as db:
                # since_id=1 → should return events with id > 1 (ids 2,3)
                events = await poll_trace_events(db, job_id, since_id=1)
            assert len(events) == 2
            assert events[0]["id"] == 2
            assert events[1]["id"] == 3

        _run(_go())


# =========================================================================
# 10. merge_status persistence in _merge_image_texts
# =========================================================================


class TestMergeStatusPersistence:
    """_merge_image_texts must commit merge_status='running', not just flush."""

    def test_merge_status_skip_when_insufficient_items(self, tmp_path):
        """_merge_image_texts sets merge_status='skipped' when < 2 items."""
        from app.features.batch_image_import_service import _merge_image_texts
        from app.models.import_batch_job import ImportBatchJob, ImportBatchJobItem

        async def _go():
            sm, _ = await _make_session(tmp_path)
            job_id = "merge_skip_001"

            async with sm() as db:
                db.add(ImportBatchJob(**_make_job(
                    job_id, status="running",
                )))
                # Only 1 succeeded item → merge should be skipped
                db.add(ImportBatchJobItem(**_make_item(
                    job_id, seq=1, status="succeeded",
                    ocr_cleaned_text="Question 1",
                    review_batch_id="OLD_BATCH",
                )))
                await db.commit()

            result = await _merge_image_texts(
                job_id=job_id, subject="math2", options={},
            )
            assert not result.get("merged")
            assert "only 1 succeeded" in result.get("reason", "").lower()

            # merge_status should be "skipped" (not stuck at "running")
            async with sm() as db:
                job = await db.get(ImportBatchJob, job_id)
                assert job is not None
                assert job.merge_status == "skipped", (
                    f"Expected 'skipped', got {job.merge_status}"
                )

        _run(_go())
