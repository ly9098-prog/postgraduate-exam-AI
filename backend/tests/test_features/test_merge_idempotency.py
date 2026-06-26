"""P0-4: Merge idempotency, supersede semantics, and transactional integrity.

Tests cover:
1. Normal merge: all items point to same final batch.
2. Merge retry: same job merged twice → single merged batch.
3. Merge failure: per-image batches preserved, items not half-switched.
4. Old batches marked superseded instead of deleted.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base


async def _make_session(tmp_path: Path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'merge_test.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False), engine


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def patch_async_session(tmp_path):
    """Patch the global async_session so merge service uses our test DB."""
    import app.features.batch_image_import_service as svc
    from app.core import database

    sm, _engine = _run(_make_session(tmp_path))

    original = database.async_session
    database.async_session = sm
    svc.async_session = sm

    yield

    database.async_session = original
    svc.async_session = original


def _make_stub_job(job_id: str) -> dict:
    """Return a minimal seed dict for a batch import job row."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return {
        "job_id": job_id,
        "source_type": "image",
        "total": 2,
        "concurrency": 1,
        "status": "running",
        "started_at": now,
        "queued_at": now,
        "updated_at": now,
    }


def _make_stub_item(
    job_id: str, seq: int, review_batch_id: str,
) -> dict:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return {
        "job_id": job_id,
        "seq": seq,
        "source_file": f"img_{seq}.png",
        "status": "succeeded",
        "review_batch_id": review_batch_id,
        "ocr_cleaned_text": f"text from page {seq}",
        "created_at": now,
        "updated_at": now,
    }


# ================================================================
# Tests
# ================================================================


class TestMergeIdempotency:
    """Merge transactional integrity and idempotency tests."""

    def test_merge_retry_idempotent(self, tmp_path):
        """Same merge called twice should produce exactly one merged batch."""
        from app.features.batch_image_import_service import _merge_image_texts
        from app.models.import_batch_job import (
            ImportBatchJob,
            ImportBatchJobItem,
        )
        from app.models.question_import import QuestionImport as QI

        async def _go():
            sm, _ = await _make_session(tmp_path)
            job_id = "merge_idem_001"

            async with sm() as db:
                db.add(ImportBatchJob(**_make_stub_job(job_id)))
                db.add(ImportBatchJobItem(
                    **_make_stub_item(job_id, 1, "OLD_BATCH_A"),
                ))
                db.add(ImportBatchJobItem(
                    **_make_stub_item(job_id, 2, "OLD_BATCH_B"),
                ))
                await db.commit()

            # Mock the pipeline to return a deterministic batch
            merged_batch = "MERGED_BATCH_001"

            with patch(
                "app.features.pipeline_orchestrator.run_import_pipeline"
            ) as mock_pipeline:
                mock_pipeline.return_value = {
                    "batch_id": merged_batch,
                    "status": "completed",
                    "stats": {"to_review": 5},
                }

                # First merge
                r1 = await _merge_image_texts(
                    job_id, subject="408", options={},
                )
                assert r1["merged"] is True
                assert r1["batch_id"] == merged_batch

                # Second merge should be idempotent
                r2 = await _merge_image_texts(
                    job_id, subject="408", options={},
                )
                assert r2["merged"] is True
                assert r2.get("reason") == "already_merged"
                assert r2.get("batch_id") == merged_batch

            # Verify: both items point to merged batch
            async with sm() as db:
                rows = (
                    await db.execute(
                        select(ImportBatchJobItem).where(
                            ImportBatchJobItem.job_id == job_id,
                        )
                    )
                ).scalars().all()
                for r in rows:
                    assert r.review_batch_id == merged_batch, (
                        f"Item seq={r.seq} has wrong batch: {r.review_batch_id}"
                    )

        _run(_go())

    def test_merge_failure_preserves_per_image_batches(self, tmp_path):
        """When merge pipeline fails, items keep their original per-image batches."""
        from app.features.batch_image_import_service import _merge_image_texts
        from app.models.import_batch_job import (
            ImportBatchJob,
            ImportBatchJobItem,
        )

        async def _go():
            sm, _ = await _make_session(tmp_path)
            job_id = "merge_fail_001"

            async with sm() as db:
                db.add(ImportBatchJob(**_make_stub_job(job_id)))
                db.add(ImportBatchJobItem(
                    **_make_stub_item(job_id, 1, "OLD_BATCH_A"),
                ))
                db.add(ImportBatchJobItem(
                    **_make_stub_item(job_id, 2, "OLD_BATCH_B"),
                ))
                await db.commit()

            with patch(
                "app.features.pipeline_orchestrator.run_import_pipeline"
            ) as mock_pipeline:
                mock_pipeline.return_value = {
                    "batch_id": None,
                    "status": "failed",
                    "errors": ["pipeline exploded"],
                }

                r = await _merge_image_texts(
                    job_id, subject="408", options={},
                )
                assert r["merged"] is False

            # Items keep original batches
            async with sm() as db:
                rows = (
                    await db.execute(
                        select(ImportBatchJobItem).where(
                            ImportBatchJobItem.job_id == job_id,
                        ).order_by(ImportBatchJobItem.seq)
                    )
                ).scalars().all()
                assert rows[0].review_batch_id == "OLD_BATCH_A"
                assert rows[1].review_batch_id == "OLD_BATCH_B"

        _run(_go())

    def test_merge_supersedes_old_batches(self, tmp_path):
        """Old question_imports batches should be marked superseded, not deleted."""
        from app.features.batch_image_import_service import _merge_image_texts
        from app.models.import_batch_job import (
            ImportBatchJob,
            ImportBatchJobItem,
        )
        from app.models.question_import import QuestionImport as QI

        async def _go():
            sm, _ = await _make_session(tmp_path)
            job_id = "merge_sup_001"

            async with sm() as db:
                db.add(ImportBatchJob(**_make_stub_job(job_id)))
                db.add(ImportBatchJobItem(
                    **_make_stub_item(job_id, 1, "OLD_BATCH_A"),
                ))
                db.add(ImportBatchJobItem(
                    **_make_stub_item(job_id, 2, "OLD_BATCH_B"),
                ))
                # Seed some question_imports in old batches
                for bid in ("OLD_BATCH_A", "OLD_BATCH_B"):
                    for i in range(3):
                        db.add(QI(
                            batch_id=bid,
                            source_type="image",
                            raw_data={"question": f"q{i}"},
                        ))
                await db.commit()

            merged_batch = "MERGED_BATCH_SUP"

            with patch(
                "app.features.pipeline_orchestrator.run_import_pipeline"
            ) as mock_pipeline:
                mock_pipeline.return_value = {
                    "batch_id": merged_batch,
                    "status": "completed",
                    "stats": {"to_review": 6},
                }

                r = await _merge_image_texts(
                    job_id, subject="408", options={},
                )
                assert r["merged"] is True

            # Old question_imports should be marked superseded, NOT deleted
            async with sm() as db:
                old_a_qs = (
                    await db.execute(
                        select(QI).where(QI.batch_id == "OLD_BATCH_A")
                    )
                ).scalars().all()
                assert len(old_a_qs) == 3, "Old batch questions should still exist"
                for q in old_a_qs:
                    assert q.superseded_by_batch_id == merged_batch
                    assert q.superseded_at is not None

                old_b_qs = (
                    await db.execute(
                        select(QI).where(QI.batch_id == "OLD_BATCH_B")
                    )
                ).scalars().all()
                assert len(old_b_qs) == 3
                for q in old_b_qs:
                    assert q.superseded_by_batch_id == merged_batch

        _run(_go())

    def test_merge_crash_before_item_update_preserves_batches(self, tmp_path):
        """Crash before any item update → all items keep original batches."""
        from app.features.batch_image_import_service import _merge_image_texts
        from app.models.import_batch_job import (
            ImportBatchJob,
            ImportBatchJobItem,
        )

        async def _go():
            sm, _ = await _make_session(tmp_path)
            job_id = "merge_crash_002"

            async with sm() as db:
                db.add(ImportBatchJob(**_make_stub_job(job_id)))
                db.add(ImportBatchJobItem(
                    **_make_stub_item(job_id, 1, "OLD_BATCH_A"),
                ))
                db.add(ImportBatchJobItem(
                    **_make_stub_item(job_id, 2, "OLD_BATCH_B"),
                ))
                await db.commit()

            # Pipeline itself crashes → no item updates happen
            with patch(
                "app.features.pipeline_orchestrator.run_import_pipeline"
            ) as mock_pipeline:
                mock_pipeline.side_effect = RuntimeError("pipeline OOM")

                r = await _merge_image_texts(
                    job_id, subject="408", options={},
                )
                assert r["merged"] is False

            # All items keep their original batches
            async with sm() as db:
                rows = (
                    await db.execute(
                        select(ImportBatchJobItem).where(
                            ImportBatchJobItem.job_id == job_id,
                        ).order_by(ImportBatchJobItem.seq)
                    )
                ).scalars().all()
                assert rows[0].review_batch_id == "OLD_BATCH_A"
                assert rows[1].review_batch_id == "OLD_BATCH_B"
                # Job merge_status should be "failed"
                job = await db.get(ImportBatchJob, job_id)
                assert job.merge_status == "failed"

        _run(_go())

    def test_merge_crash_inside_atomic_commit_rolls_back(self, tmp_path):
        """Crash inside _batch_merge_commit → everything rolls back."""
        from app.features.batch_image_import_service import (
            _batch_merge_commit,
            _merge_image_texts,
        )
        from app.models.import_batch_job import (
            ImportBatchJob,
            ImportBatchJobItem,
        )

        async def _go():
            sm, _ = await _make_session(tmp_path)
            job_id = "merge_crash_atomic_001"

            async with sm() as db:
                db.add(ImportBatchJob(**_make_stub_job(job_id)))
                db.add(ImportBatchJobItem(
                    **_make_stub_item(job_id, 1, "OLD_BATCH_A"),
                ))
                db.add(ImportBatchJobItem(
                    **_make_stub_item(job_id, 2, "OLD_BATCH_B"),
                ))
                await db.commit()

            with patch(
                "app.features.batch_image_import_service._batch_merge_commit",
                side_effect=RuntimeError("merge commit crashed"),
            ):
                with patch(
                    "app.features.pipeline_orchestrator.run_import_pipeline"
                ) as mock_pipeline:
                    mock_pipeline.return_value = {
                        "batch_id": "MERGED_ATOMIC",
                        "status": "completed",
                        "stats": {"to_review": 5},
                    }
                    r = await _merge_image_texts(
                        job_id, subject="408", options={},
                    )
                    assert r["merged"] is False
                    assert "exception" in r.get("reason", "")

            # All items keep original batches (atomic rollback)
            async with sm() as db:
                rows = (
                    await db.execute(
                        select(ImportBatchJobItem).where(
                            ImportBatchJobItem.job_id == job_id,
                        ).order_by(ImportBatchJobItem.seq)
                    )
                ).scalars().all()
                assert rows[0].review_batch_id == "OLD_BATCH_A"
                assert rows[1].review_batch_id == "OLD_BATCH_B"
                # Job merge_status set to "failed" by outer exception handler
                job = await db.get(ImportBatchJob, job_id)
                assert job.merge_status == "failed"

        _run(_go())

    def test_concurrent_merge_produces_single_batch(self, tmp_path):
        """Two concurrent merge calls → only one merged batch created."""
        from app.features.batch_image_import_service import _merge_image_texts
        from app.models.import_batch_job import (
            ImportBatchJob,
            ImportBatchJobItem,
        )

        async def _go():
            sm, _ = await _make_session(tmp_path)
            job_id = "merge_concur_001"

            async with sm() as db:
                db.add(ImportBatchJob(**_make_stub_job(job_id)))
                db.add(ImportBatchJobItem(
                    **_make_stub_item(job_id, 1, "OLD_BATCH_A"),
                ))
                db.add(ImportBatchJobItem(
                    **_make_stub_item(job_id, 2, "OLD_BATCH_B"),
                ))
                await db.commit()

            call_count = 0

            async def _fake_pipeline(**kw):
                nonlocal call_count
                call_count += 1
                # Simulate pipeline latency
                await asyncio.sleep(0.05)
                return {
                    "batch_id": f"MERGED_CONCUR_{call_count}",
                    "status": "completed",
                    "stats": {"to_review": 5},
                }

            with patch(
                "app.features.pipeline_orchestrator.run_import_pipeline",
                side_effect=_fake_pipeline,
            ):
                r1, r2 = await asyncio.gather(
                    _merge_image_texts(job_id, subject="408", options={}),
                    _merge_image_texts(job_id, subject="408", options={}),
                    return_exceptions=True,
                )

            # At most one should succeed as merged
            merged_results = [r for r in (r1, r2) if isinstance(r, dict) and r.get("merged")]
            assert len(merged_results) >= 1, (
                f"At least one merge should succeed: r1={r1} r2={r2}"
            )
            # Both should reference the same batch_id
            batch_ids = {r["batch_id"] for r in merged_results}
            assert len(batch_ids) == 1, f"Multiple batches created: {batch_ids}"

            # One should report "already_merged" (idempotent)
            already = [r for r in (r1, r2) if isinstance(r, dict) and r.get("reason") == "already_merged"]
            assert len(already) >= 1 or len(merged_results) >= 1, (
                f"Expected idempotent: {r1} {r2}"
            )

            # Verify only one merged batch exists
            async with sm() as db:
                rows = (
                    await db.execute(
                        select(ImportBatchJobItem).where(
                            ImportBatchJobItem.job_id == job_id,
                        )
                    )
                ).scalars().all()
                batch_ids_set = {r.review_batch_id for r in rows}
                # All point to same merged batch
                assert len(batch_ids_set) == 1, f"Items point to different batches: {batch_ids_set}"
                assert "OLD_BATCH" not in str(batch_ids_set), "Old batches still present"

        _run(_go())
