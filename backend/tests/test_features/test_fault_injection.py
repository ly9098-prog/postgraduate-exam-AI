"""P0-6: Fault injection — resilience under adverse conditions.

Tests cover:
1. Cache unavailable during pipeline store write
2. AI API timeout during pipeline
3. Concurrent duplicate merge (race condition)
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base


async def _make_session(tmp_path: Path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'fault_test.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False), engine


def _run(coro):
    return asyncio.run(coro)


# ================================================================
# Cache fault injection
# ================================================================


class TestCacheUnavailable:
    """Redis/cache unavailable should not break pipeline status writes."""

    def test_set_pipeline_store_cache_fails_gracefully(self):
        """When cache.set raises, pipeline store should still work in-memory."""
        from app.features.pipeline_orchestrator import (
            _pipeline_store,
            _set_pipeline_store,
        )

        pid = "fault_cache_001"
        _pipeline_store.pop(pid, None)

        with patch("app.core.cache.cache.set") as mock_set:
            mock_set.side_effect = RuntimeError("Redis connection refused")
            _run(_set_pipeline_store(pid, {
                "pipeline_id": pid,
                "status": "running",
                "source_type": "txt",
                "stages": {},
                "stats": {},
                "errors": [],
                "started_at": "2026-06-25T00:00:00",
            }))

        assert pid in _pipeline_store
        assert _pipeline_store[pid]["status"] == "running"

        # Cleanup
        _pipeline_store.pop(pid, None)

    def test_get_pipeline_status_cache_fails_falls_back_to_memory(self):
        """When cache.get raises, get_pipeline_status falls back to in-memory."""
        from app.features.pipeline_orchestrator import (
            _pipeline_store,
            _set_pipeline_store,
            get_pipeline_status,
        )

        pid = "fault_cache_002"
        _pipeline_store.pop(pid, None)

        _run(_set_pipeline_store(pid, {
            "pipeline_id": pid,
            "status": "running",
            "source_type": "txt",
            "stages": {},
            "stats": {},
            "errors": [],
            "started_at": "2026-06-25T00:00:00",
        }))

        # Now simulate cache failure during read
        with patch("app.core.cache.cache.get") as mock_get:
            mock_get.side_effect = RuntimeError("Cache unavailable")
            status = _run(get_pipeline_status(pid))

        assert status is not None
        assert status["status"] == "running"

        # Cleanup
        _pipeline_store.pop(pid, None)

    def test_image_pipeline_cache_fails_gracefully(self):
        """Image pipeline status write with cache failure."""
        from app.api.v1.imports import (
            _image_pipeline_store,
            _set_image_pipeline_status,
        )

        pid = "fault_img_cache_001"
        _image_pipeline_store.pop(pid, None)

        with patch("app.api.v1.imports.cache.set") as mock_set:
            mock_set.side_effect = RuntimeError("Redis connection refused")
            status = _run(_set_image_pipeline_status(
                pid,
                status="running",
            ))

        assert status["status"] == "running"
        assert pid in _image_pipeline_store

        # Cleanup
        _image_pipeline_store.pop(pid, None)


# ================================================================
# AI API fault injection
# ================================================================


class TestAiApiTimeout:
    """AI API timeout/unavailable should degrade gracefully."""

    @pytest.mark.asyncio
    async def test_ocr_correction_ai_timeout(self):
        """AI timeout in OCR correction returns original blocks."""
        from app.features.ocr_correction import correct_ocr_blocks

        blocks = [{
            "page": 1,
            "block_index": 0,
            "normalized_text": "1.\n下列\n关于\n数据\n结构",
        }]

        with patch("app.ai.client.deepseek") as mock_client, \
             patch("app.features.ocr_fix.OCRFixRouter") as mock_router_cls:
            mock_client.is_available.return_value = True
            mock_router = MagicMock()
            mock_router.fix = AsyncMock(side_effect=TimeoutError("AI API timeout"))
            mock_router.configure = MagicMock()
            mock_router_cls.return_value = mock_router

            result = await correct_ocr_blocks(blocks, {
                "enabled": True,
                "mode": "always",
            })

        assert result["stats"]["corrected_blocks"] == 0
        assert result["corrected_blocks"][0]["normalized_text"] == blocks[0]["normalized_text"]

    @pytest.mark.asyncio
    async def test_ocr_correction_ai_unavailable(self):
        """AI unavailable skips correction entirely."""
        from app.features.ocr_correction import correct_ocr_blocks

        blocks = [{
            "page": 1,
            "block_index": 0,
            "normalized_text": "1. 测试题目文本",
        }]

        with patch("app.ai.client.deepseek") as mock_client:
            mock_client.is_available.return_value = False

            result = await correct_ocr_blocks(blocks, {"enabled": True})

        assert result["skipped_reason"] == "ai_unavailable"
        assert result["stats"]["corrected_blocks"] == 0



# ================================================================
# Concurrent duplicate merge
# ================================================================


class TestConcurrentMerge:
    """Concurrent duplicate merge should not create duplicate batches."""

    def test_concurrent_merge_same_batch_id(self, tmp_path):
        """Two concurrent merge calls for the same job produce single batch."""
        from app.features.batch_image_import_service import _merge_image_texts
        from app.models.import_batch_job import (
            ImportBatchJob,
            ImportBatchJobItem,
        )

        async def _go():
            sm, eng = await _make_session(tmp_path)
            # Override the global session so the merge service uses our test DB
            import app.features.batch_image_import_service as svc
            from app.core import database
            orig_session = database.async_session
            database.async_session = sm
            svc.async_session = sm

            job_id = "fault_con_merge_001"

            async with sm() as db:
                db.add(ImportBatchJob(**_make_stub_job(job_id)))
                db.add(ImportBatchJobItem(
                    **_make_stub_item(job_id, 1, "BATCH_A"),
                ))
                db.add(ImportBatchJobItem(
                    **_make_stub_item(job_id, 2, "BATCH_B"),
                ))
                await db.commit()

            merged_batch = "CON_MERGE_BATCH_001"
            call_count = 0

            async def _pipeline_side(*_args, **_kw):
                nonlocal call_count
                call_count += 1
                return {"batch_id": merged_batch, "status": "completed", "stats": {"to_review": 5}}

            with patch(
                "app.features.pipeline_orchestrator.run_import_pipeline",
                side_effect=_pipeline_side,
            ):
                r1, r2 = await asyncio.gather(
                    _merge_image_texts(job_id, subject="408", options={}),
                    _merge_image_texts(job_id, subject="408", options={}),
                )

            # At least one succeeded
            assert r1["merged"] is True or r2["merged"] is True
            assert call_count >= 1

            async with sm() as db:
                items = (
                    await db.execute(
                        select(ImportBatchJobItem).where(
                            ImportBatchJobItem.job_id == job_id
                        )
                    )
                ).scalars().all()
                final_batch_ids = {i.review_batch_id for i in items}

            # Both items should end up in the same batch
            assert len(final_batch_ids) == 1, (
                f"Expected single batch, got {final_batch_ids}"
            )

            database.async_session = orig_session
            svc.async_session = orig_session
            await eng.dispose()

        asyncio.run(_go())


def _make_stub_job(job_id: str) -> dict:
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
