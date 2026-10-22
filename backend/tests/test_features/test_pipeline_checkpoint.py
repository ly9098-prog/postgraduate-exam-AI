"""P2-1 import_pipeline checkpoint 单测。

用真实 sqlite+aiosqlite + Base.metadata.create_all 跑，避免 mock session 把
SQL 行为也 mock 掉导致测试和实际 DB 行为脱节。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.database import Base
from app.features.pipeline_checkpoint import (
    create_chunk_records,
    create_pipeline_record,
    ensure_chunk_records,
    ensure_pipeline_record,
    get_pending_chunks,
    get_pipeline_progress,
    mark_chunk_running,
    set_fencing_context,
    clear_fencing_context,
    update_chunk_status,
    update_pipeline_metadata,
    update_pipeline_status,
)
from app.models.import_pipeline import ImportPipeline, ImportPipelineChunk  # noqa: F401


async def _make_session(tmp_path) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'p2_checkpoint.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    return sessionmaker, engine


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


# ---------------------------------------------------------------------------
# create / update pipeline
# ---------------------------------------------------------------------------


def test_create_pipeline_record_writes_row(tmp_path):
    async def _go():
        sm, _engine = await _make_session(tmp_path)
        async with sm() as db:
            row = await create_pipeline_record(
                db,
                pipeline_id="pl_test_001",
                source_type="pdf",
                source_file="王道.pdf",
                total_pages=120,
                chunk_size=40,
            )
            assert row.pipeline_id == "pl_test_001"
            assert row.status == "running"
            assert row.total_pages == 120
            assert row.chunk_size == 40
            # P0-1 / P0-2: 不传 kwargs 时默认 NULL，向后兼容老调用方
            assert row.created_by is None
            assert row.source_sha256 is None

    _run(_go())


def test_create_pipeline_record_persists_owner_and_hash(tmp_path):
    """P0-1 / P0-2: created_by + source_sha256 写入后能从 DB 读回。"""
    from sqlalchemy import select

    async def _go():
        sm, _engine = await _make_session(tmp_path)
        async with sm() as db:
            await create_pipeline_record(
                db,
                pipeline_id="pl_security_001",
                source_type="pdf",
                source_file="王道.pdf",
                total_pages=120,
                chunk_size=40,
                created_by="u1",
                source_sha256="abc" + "0" * 61,
            )

        async with sm() as db:
            row = (
                await db.execute(
                    select(ImportPipeline).where(
                        ImportPipeline.pipeline_id == "pl_security_001"
                    )
                )
            ).scalar_one()
            assert row.created_by == "u1"
            assert row.source_sha256 == "abc" + "0" * 61

    _run(_go())


def test_create_pipeline_record_persists_watermark_snapshot(tmp_path):
    """P0-3: watermark_snapshot 写入后能从 DB 读回（list[dict] 结构）。"""
    from sqlalchemy import select

    snapshot = [
        {"pattern": r"^内部资料$", "flags": 0},
        {"pattern": r"^第\s*\d+\s*页$", "flags": 0},
    ]

    async def _go():
        sm, _engine = await _make_session(tmp_path)
        async with sm() as db:
            await create_pipeline_record(
                db,
                pipeline_id="pl_wm_snapshot_001",
                source_type="pdf",
                source_file="x.pdf",
                total_pages=120,
                chunk_size=40,
                watermark_snapshot=snapshot,
            )

        async with sm() as db:
            row = (
                await db.execute(
                    select(ImportPipeline).where(
                        ImportPipeline.pipeline_id == "pl_wm_snapshot_001"
                    )
                )
            ).scalar_one()
            assert row.watermark_snapshot == snapshot

    _run(_go())


def test_ensure_pipeline_record_is_idempotent_and_enriches_owner(tmp_path):
    async def _go():
        sm, _engine = await _make_session(tmp_path)
        async with sm() as db:
            admitted = await ensure_pipeline_record(
                db,
                pipeline_id="pl_ensure_001",
                source_type="pdf",
                source_file="upload.pdf",
                total_pages=None,
                chunk_size=40,
                created_by="admin-1",
                source_sha256="a" * 64,
                status="queued",
            )
            assert admitted.status == "queued"
            assert admitted.created_by == "admin-1"
            assert admitted.source_sha256 == "a" * 64

            enriched = await ensure_pipeline_record(
                db,
                pipeline_id="pl_ensure_001",
                source_type="pdf",
                source_file="upload.pdf",
                total_pages=120,
                chunk_size=40,
                created_by="different-admin",
                source_sha256="b" * 64,
                status="processing",
            )
            assert enriched.total_pages == 120
            assert enriched.status == "processing"
            # Owner/hash are immutable once admitted.
            assert enriched.created_by == "admin-1"
            assert enriched.source_sha256 == "a" * 64

    _run(_go())


def test_ensure_chunk_records_is_idempotent_and_rejects_range_changes(tmp_path):
    async def _go():
        sm, _engine = await _make_session(tmp_path)
        async with sm() as db:
            await ensure_pipeline_record(
                db,
                pipeline_id="pl_ensure_chunks",
                source_type="pdf",
                source_file="upload.pdf",
                total_pages=120,
                chunk_size=40,
                status="queued",
            )
            first = await ensure_chunk_records(
                db, "pl_ensure_chunks", [(1, 40), (41, 80), (81, 120)]
            )
            second = await ensure_chunk_records(
                db, "pl_ensure_chunks", [(1, 40), (41, 80), (81, 120)]
            )
            assert [chunk.chunk_index for chunk in first] == [0, 1, 2]
            assert [chunk.chunk_index for chunk in second] == [0, 1, 2]

            with pytest.raises(ValueError, match="range changed"):
                await ensure_chunk_records(
                    db, "pl_ensure_chunks", [(1, 40), (41, 80), (81, 119)]
                )

    _run(_go())


def test_stale_fence_rejects_parent_and_chunk_updates(tmp_path):
    async def _go():
        sm, _engine = await _make_session(tmp_path)
        async with sm() as db:
            await ensure_pipeline_record(
                db,
                pipeline_id="pl_fence_001",
                source_type="pdf",
                source_file="upload.pdf",
                total_pages=40,
                chunk_size=40,
                status="processing",
            )
            await ensure_chunk_records(db, "pl_fence_001", [(1, 40)])

            from app.models.import_pipeline import ImportPipeline
            from sqlalchemy import update

            await db.execute(
                update(ImportPipeline)
                .where(ImportPipeline.pipeline_id == "pl_fence_001")
                .values(
                    current_task_id="new-task",
                    current_owner_token="new-owner",
                    execution_generation=2,
                )
            )
            await db.commit()

            token = set_fencing_context(
                task_id="stale-task", owner_token="stale-owner", generation=1
            )
            try:
                from app.services.db_fencing import FencingRejectedError

                with pytest.raises(FencingRejectedError, match="record update"):
                    await ensure_pipeline_record(
                        db,
                        pipeline_id="pl_fence_001",
                        source_type="pdf",
                        source_file="upload.pdf",
                        total_pages=40,
                        chunk_size=40,
                        status="completed",
                    )
                with pytest.raises(FencingRejectedError, match="Chunk update"):
                    await update_chunk_status(
                        db, "pl_fence_001", 0, status="completed"
                    )
                with pytest.raises(FencingRejectedError, match="metadata update"):
                    await update_pipeline_metadata(
                        db, "pl_fence_001", alerts=[{"code": "stale"}]
                    )
            finally:
                clear_fencing_context(token)

    _run(_go())


def test_update_pipeline_status_marks_finished(tmp_path):
    async def _go():
        sm, _engine = await _make_session(tmp_path)
        async with sm() as db:
            await create_pipeline_record(
                db,
                pipeline_id="pl_test_002",
                source_type="pdf",
                source_file=None,
                total_pages=80,
                chunk_size=40,
            )
            await update_pipeline_status(
                db, "pl_test_002", status="completed", finished=True
            )

        async with sm() as db:
            progress = await get_pipeline_progress(db, "pl_test_002", use_cache=False)
            assert progress is not None
            assert progress["status"] == "completed"
            assert progress["finished_at"] is not None

    _run(_go())


# ---------------------------------------------------------------------------
# create chunk records + status transitions
# ---------------------------------------------------------------------------


def test_create_chunk_records_initializes_pending(tmp_path):
    async def _go():
        sm, _engine = await _make_session(tmp_path)
        async with sm() as db:
            await create_pipeline_record(
                db,
                pipeline_id="pl_chunk_001",
                source_type="pdf",
                source_file=None,
                total_pages=120,
                chunk_size=40,
            )
            chunks = await create_chunk_records(
                db,
                "pl_chunk_001",
                page_ranges=[(1, 40), (41, 80), (81, 120)],
            )
            assert len(chunks) == 3
            assert [c.chunk_index for c in chunks] == [0, 1, 2]
            assert all(c.status == "pending" for c in chunks)
            assert chunks[0].page_start == 1 and chunks[0].page_end == 40
            assert chunks[2].page_end == 120

    _run(_go())


def test_chunk_status_transitions(tmp_path):
    async def _go():
        sm, _engine = await _make_session(tmp_path)
        async with sm() as db:
            await create_pipeline_record(
                db,
                pipeline_id="pl_chunk_002",
                source_type="pdf",
                source_file=None,
                total_pages=80,
                chunk_size=40,
            )
            await create_chunk_records(
                db, "pl_chunk_002", page_ranges=[(1, 40), (41, 80)]
            )

            await mark_chunk_running(db, "pl_chunk_002", 0)
            await update_chunk_status(
                db,
                "pl_chunk_002",
                0,
                status="completed",
                batch_id="REVIEW_xxx",
                question_count=37,
            )
            await mark_chunk_running(db, "pl_chunk_002", 1)
            await update_chunk_status(
                db,
                "pl_chunk_002",
                1,
                status="failed",
                error_message="OCR timeout on page 65",
            )

        async with sm() as db:
            progress = await get_pipeline_progress(db, "pl_chunk_002", use_cache=False)
            assert progress["total_chunks"] == 2
            assert progress["completed_chunks"] == 1
            assert progress["failed_chunks"] == 1
            assert progress["pending_chunks"] == 0
            assert progress["running_chunks"] == 0
            # 只统计 completed 的 question_count
            assert progress["question_count"] == 37
            assert len(progress["failed_chunk_details"]) == 1
            assert progress["failed_chunk_details"][0]["chunk_index"] == 1
            assert "OCR timeout" in progress["failed_chunk_details"][0]["error_message"]

    _run(_go())


# ---------------------------------------------------------------------------
# get_pipeline_progress
# ---------------------------------------------------------------------------


def test_get_progress_returns_none_for_missing_pipeline(tmp_path):
    async def _go():
        sm, _engine = await _make_session(tmp_path)
        async with sm() as db:
            assert await get_pipeline_progress(db, "no_such_pipeline", use_cache=False) is None

    _run(_go())


def test_progress_includes_full_status_breakdown(tmp_path):
    """统计字段：total/completed/failed/running/pending 各自正确。"""
    async def _go():
        sm, _engine = await _make_session(tmp_path)
        async with sm() as db:
            await create_pipeline_record(
                db,
                pipeline_id="pl_progress",
                source_type="pdf",
                source_file=None,
                total_pages=200,
                chunk_size=40,
            )
            await create_chunk_records(
                db,
                "pl_progress",
                page_ranges=[(1, 40), (41, 80), (81, 120), (121, 160), (161, 200)],
            )
            # 0 完成、1 完成、2 失败、3 运行中、4 保持 pending
            await update_chunk_status(db, "pl_progress", 0, status="completed", question_count=30)
            await update_chunk_status(db, "pl_progress", 1, status="completed", question_count=20)
            await update_chunk_status(db, "pl_progress", 2, status="failed", error_message="x")
            await mark_chunk_running(db, "pl_progress", 3)

        async with sm() as db:
            progress = await get_pipeline_progress(db, "pl_progress", use_cache=False)
            assert progress["total_chunks"] == 5
            assert progress["completed_chunks"] == 2
            assert progress["failed_chunks"] == 1
            assert progress["running_chunks"] == 1
            assert progress["pending_chunks"] == 1
            assert progress["question_count"] == 50

    _run(_go())


# ---------------------------------------------------------------------------
# get_pending_chunks (resume)
# ---------------------------------------------------------------------------


def test_pending_chunks_returns_failed_and_pending(tmp_path):
    """resume 应该拿到 failed + pending（不含 running，不含 completed）。"""
    async def _go():
        sm, _engine = await _make_session(tmp_path)
        async with sm() as db:
            await create_pipeline_record(
                db,
                pipeline_id="pl_resume",
                source_type="pdf",
                source_file=None,
                total_pages=160,
                chunk_size=40,
            )
            await create_chunk_records(
                db,
                "pl_resume",
                page_ranges=[(1, 40), (41, 80), (81, 120), (121, 160)],
            )
            await update_chunk_status(db, "pl_resume", 0, status="completed", question_count=10)
            await update_chunk_status(db, "pl_resume", 1, status="failed", error_message="x")
            await mark_chunk_running(db, "pl_resume", 2)
            # chunk 3 保持 pending

        async with sm() as db:
            pending = await get_pending_chunks(db, "pl_resume")
            indices = [c.chunk_index for c in pending]
            assert indices == [1, 3]  # failed + pending，按 index 排序
            statuses = {c.chunk_index: c.status for c in pending}
            assert statuses[1] == "failed"
            assert statuses[3] == "pending"

    _run(_go())


def test_unique_constraint_blocks_duplicate_chunk_index(tmp_path):
    """同一 pipeline 不能有两个 chunk_index 相同的 chunk。"""
    async def _go():
        sm, _engine = await _make_session(tmp_path)
        async with sm() as db:
            await create_pipeline_record(
                db,
                pipeline_id="pl_unique",
                source_type="pdf",
                source_file=None,
                total_pages=40,
                chunk_size=40,
            )
            await create_chunk_records(
                db, "pl_unique", page_ranges=[(1, 40)]
            )

        async with sm() as db:
            with pytest.raises(Exception):  # IntegrityError 在 sqlite/pg 都会抛
                db.add(
                    ImportPipelineChunk(
                        pipeline_id="pl_unique",
                        chunk_index=0,
                        page_start=1,
                        page_end=40,
                        status="pending",
                    )
                )
                await db.commit()

    _run(_go())
