"""P0-5: SSE terminal event must depend on committed merge.

Tests cover poll_job_summary behavior at each lifecycle stage:
1. Items done, merge not started → job.status == "running"
2. Merge in progress → job.status == "merging"
3. Merge committed, job status updated → job.status == "completed"
4. Merge failed → job.status has warning but is still terminal
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base


async def _make_session(tmp_path: Path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'sse_test.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False), engine


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def patch_async_session(tmp_path):
    """Patch global async_session so merge service uses test DB."""
    import app.features.batch_image_import_service as svc
    from app.core import database

    sm, _engine = _run(_make_session(tmp_path))

    original = database.async_session
    database.async_session = sm
    svc.async_session = sm

    yield

    database.async_session = original
    svc.async_session = original


def _make_stub_job(job_id: str, **overrides) -> dict:
    from datetime import datetime
    now = datetime.now().astimezone().replace(tzinfo=None)
    defaults = {
        "job_id": job_id,
        "source_type": "image",
        "total": 2,
        "concurrency": 1,
        "status": "running",
        "started_at": now,
        "queued_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return defaults


def _make_stub_item(job_id: str, seq: int, review_batch_id: str, **overrides) -> dict:
    from datetime import datetime
    now = datetime.now().astimezone().replace(tzinfo=None)
    defaults = {
        "job_id": job_id,
        "seq": seq,
        "source_file": f"img_{seq}.png",
        "status": "succeeded",
        "review_batch_id": review_batch_id,
        "ocr_cleaned_text": f"text from page {seq}",
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return defaults


class TestSSEMergeTerminal:
    """SSE must not send terminal event before merge is fully committed."""

    def test_poll_summary_job_running_merge_not_started(self, tmp_path):
        """Items complete, merge not started → job.status == 'running'."""
        from app.features.batch_image_import_service import poll_job_summary
        from app.models.import_batch_job import ImportBatchJob, ImportBatchJobItem

        async def _go():
            sm, _ = await _make_session(tmp_path)
            job_id = "sse_running_001"

            async with sm() as db:
                db.add(ImportBatchJob(**_make_stub_job(job_id, status="running")))
                db.add(ImportBatchJobItem(
                    **_make_stub_item(job_id, 1, "BATCH_A", status="succeeded"),
                ))
                db.add(ImportBatchJobItem(
                    **_make_stub_item(job_id, 2, "BATCH_B", status="succeeded"),
                ))
                await db.commit()

            async with sm() as db:
                summary = await poll_job_summary(db, job_id)

            assert summary is not None
            assert summary["status"] == "running", (
                f"Expected running, got {summary['status']}"
            )

        _run(_go())

    def test_poll_summary_job_merging_not_terminal(self, tmp_path):
        """Merge in progress → job.status == 'merging', not 'completed'."""
        from app.features.batch_image_import_service import poll_job_summary
        from app.models.import_batch_job import ImportBatchJob, ImportBatchJobItem

        async def _go():
            sm, _ = await _make_session(tmp_path)
            job_id = "sse_merging_001"

            async with sm() as db:
                db.add(ImportBatchJob(**_make_stub_job(
                    job_id, status="merging", merge_status="running",
                )))
                db.add(ImportBatchJobItem(
                    **_make_stub_item(job_id, 1, "BATCH_A", status="succeeded"),
                ))
                db.add(ImportBatchJobItem(
                    **_make_stub_item(job_id, 2, "BATCH_B", status="succeeded"),
                ))
                await db.commit()

            async with sm() as db:
                summary = await poll_job_summary(db, job_id)

            assert summary is not None
            assert summary["status"] == "merging", (
                f"Expected merging, got {summary['status']}"
            )

        _run(_go())

    def test_poll_summary_job_completed_after_merge(self, tmp_path):
        """Merge done, job terminal → job.status == 'completed'."""
        from app.features.batch_image_import_service import poll_job_summary
        from app.models.import_batch_job import ImportBatchJob, ImportBatchJobItem

        async def _go():
            sm, _ = await _make_session(tmp_path)
            job_id = "sse_done_001"

            async with sm() as db:
                db.add(ImportBatchJob(**_make_stub_job(
                    job_id, status="completed",
                    merge_status="completed", merged_batch_id="MERGED",
                )))
                db.add(ImportBatchJobItem(
                    **_make_stub_item(job_id, 1, "MERGED", status="succeeded"),
                ))
                db.add(ImportBatchJobItem(
                    **_make_stub_item(job_id, 2, "MERGED", status="succeeded"),
                ))
                await db.commit()

            async with sm() as db:
                summary = await poll_job_summary(db, job_id)

            assert summary is not None
            assert summary["status"] == "completed", (
                f"Expected completed, got {summary['status']}"
            )

        _run(_go())

    def test_poll_summary_merge_failed_job_still_terminal(self, tmp_path):
        """Merge failed → job.status is 'completed' (with warning), still terminal."""
        from app.features.batch_image_import_service import poll_job_summary
        from app.models.import_batch_job import ImportBatchJob, ImportBatchJobItem

        async def _go():
            sm, _ = await _make_session(tmp_path)
            job_id = "sse_merge_fail_001"

            async with sm() as db:
                db.add(ImportBatchJob(**_make_stub_job(
                    job_id, status="completed", merge_status="failed",
                    merge_error="merge pipeline error",
                    finished_at=None,
                )))
                db.add(ImportBatchJobItem(
                    **_make_stub_item(job_id, 1, "BATCH_A", status="succeeded"),
                ))
                db.add(ImportBatchJobItem(
                    **_make_stub_item(job_id, 2, "BATCH_B", status="succeeded"),
                ))
                await db.commit()

            async with sm() as db:
                summary = await poll_job_summary(db, job_id)

            assert summary is not None
            assert summary["status"] == "completed", (
                f"Expected completed, got {summary['status']}"
            )
            # Error message may be present

        _run(_go())

    def test_sse_reconnect_shows_final_state(self, tmp_path):
        """Reconnected SSE client reads final state without re-merging."""
        from app.features.batch_image_import_service import poll_job_summary
        from app.models.import_batch_job import ImportBatchJob, ImportBatchJobItem

        async def _go():
            sm, _ = await _make_session(tmp_path)
            job_id = "sse_reconnect_001"

            async with sm() as db:
                db.add(ImportBatchJob(**_make_stub_job(
                    job_id, status="completed", merged_batch_id="MERGED",
                    merge_status="completed",
                )))
                db.add(ImportBatchJobItem(
                    **_make_stub_item(job_id, 1, "MERGED", status="succeeded"),
                ))
                db.add(ImportBatchJobItem(
                    **_make_stub_item(job_id, 2, "MERGED", status="succeeded"),
                ))
                await db.commit()

            # Verify: summary shows completed
            async with sm() as db:
                summary = await poll_job_summary(db, job_id)
            assert summary["status"] == "completed"

        _run(_go())
