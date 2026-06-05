"""P2-6 status API + chunk_progress 合并视图测试。

verifies:
- chunked PDF 路径：``get_pipeline_status(pipeline_id, db=...)`` 把
  pipeline_checkpoint.get_pipeline_progress 的结果合并到 ``chunk_progress``。
- legacy（无 db / 无 chunk 记录）：``chunk_progress`` 字段缺失，向后兼容
  图片 / Excel / 单 pass。
- 主 store 不被污染：合并后再次查询，``_pipeline_store`` 内仍只持有
  ``_PIPELINE_STORE_FIELDS`` 白名单字段。
"""

from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.features import pipeline_orchestrator as orch
from app.features.pipeline_checkpoint import (
    create_chunk_records,
    create_pipeline_record,
    update_chunk_status,
)
from app.models.import_pipeline import ImportPipeline, ImportPipelineChunk  # noqa: F401


def _run(coro):
    return asyncio.run(coro)


async def _make_sessionmaker(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'p2_status.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False), engine


def _seed_main_store(pipeline_id: str) -> None:
    """直接写主 store 模拟 chunked pipeline 已落进 _pipeline_store 的状态。"""
    orch._pipeline_store[pipeline_id] = {
        "pipeline_id": pipeline_id,
        "status": "paused",
        "source_type": "pdf",
        "source_file": "wangdao.pdf",
        "stages": {},
        "stats": {"total_chunks": 3, "completed_chunks": 2, "failed_chunks": 1},
        "errors": [],
        "started_at": "2026-06-05T10:00:00",
        "finished_at": "",
        "batch_id": "",
        "raw_text_preview": "",
        "question_count": 50,
    }


def test_status_includes_chunk_progress_when_db_provided(tmp_path):
    """db 注入时 chunk_progress 字段从 import_pipeline_chunks 聚合得到。"""

    async def _go():
        sm, _engine = await _make_sessionmaker(tmp_path)
        pipeline_id = "pl_p26_001"

        async with sm() as db:
            await create_pipeline_record(
                db,
                pipeline_id=pipeline_id,
                source_type="pdf",
                source_file="wangdao.pdf",
                total_pages=120,
                chunk_size=40,
            )
            await create_chunk_records(
                db,
                pipeline_id,
                page_ranges=[(1, 40), (41, 80), (81, 120)],
            )
            await update_chunk_status(
                db, pipeline_id, 0,
                status="completed", batch_id="REVIEW_a", question_count=30,
            )
            await update_chunk_status(
                db, pipeline_id, 1,
                status="failed", error_message="OCR timeout",
            )
            await update_chunk_status(
                db, pipeline_id, 2,
                status="completed", batch_id="REVIEW_c", question_count=20,
            )

        _seed_main_store(pipeline_id)
        try:
            async with sm() as db:
                status = await orch.get_pipeline_status(pipeline_id, db=db)
            assert status is not None
            assert "chunk_progress" in status
            cp = status["chunk_progress"]
            assert cp["total_chunks"] == 3
            assert cp["completed_chunks"] == 2
            assert cp["failed_chunks"] == 1
            assert cp["pending_chunks"] == 0
            assert cp["question_count"] == 50  # only completed chunks summed
            assert len(cp["failed_chunk_details"]) == 1
            assert cp["failed_chunk_details"][0]["chunk_index"] == 1
            assert "OCR timeout" in cp["failed_chunk_details"][0]["error_message"]
        finally:
            orch._pipeline_store.pop(pipeline_id, None)

    _run(_go())


def test_status_omits_chunk_progress_when_db_none(tmp_path):
    """db=None（image / excel / 单 pass 路径）时不附加 chunk_progress。"""
    pipeline_id = "pl_p26_002"
    _seed_main_store(pipeline_id)
    try:
        status = asyncio.run(orch.get_pipeline_status(pipeline_id))
        assert status is not None
        assert "chunk_progress" not in status
    finally:
        orch._pipeline_store.pop(pipeline_id, None)


def test_status_omits_chunk_progress_when_pipeline_has_no_chunks(tmp_path):
    """db 注入但 import_pipelines 表无该记录（如单 pass / excel）。"""

    async def _go():
        sm, _engine = await _make_sessionmaker(tmp_path)
        pipeline_id = "pl_p26_003"
        _seed_main_store(pipeline_id)
        try:
            async with sm() as db:
                status = await orch.get_pipeline_status(pipeline_id, db=db)
            assert status is not None
            # get_pipeline_progress 在没有记录时返回 None → 不写 chunk_progress
            assert "chunk_progress" not in status
        finally:
            orch._pipeline_store.pop(pipeline_id, None)

    _run(_go())


def test_status_query_does_not_pollute_main_store_with_chunk_progress(tmp_path):
    """合并 chunk_progress 必须走 dict(data) 拷贝，主 store 仍只含白名单字段。"""

    async def _go():
        sm, _engine = await _make_sessionmaker(tmp_path)
        pipeline_id = "pl_p26_004"

        async with sm() as db:
            await create_pipeline_record(
                db,
                pipeline_id=pipeline_id,
                source_type="pdf",
                source_file=None,
                total_pages=80,
                chunk_size=40,
            )
            await create_chunk_records(
                db, pipeline_id, page_ranges=[(1, 40), (41, 80)]
            )
            await update_chunk_status(
                db, pipeline_id, 0,
                status="completed", batch_id="REVIEW_a", question_count=10,
            )
            await update_chunk_status(
                db, pipeline_id, 1,
                status="completed", batch_id="REVIEW_b", question_count=12,
            )

        _seed_main_store(pipeline_id)
        try:
            async with sm() as db:
                # 多次查询模拟 polling，主 store 不能膨胀
                for _ in range(3):
                    snapshot = await orch.get_pipeline_status(pipeline_id, db=db)
                    assert "chunk_progress" in snapshot

            stored = orch._pipeline_store[pipeline_id]
            assert "chunk_progress" not in stored
            assert "diagnostics" not in stored
            assert set(stored.keys()).issubset(set(orch._PIPELINE_STORE_FIELDS))
        finally:
            orch._pipeline_store.pop(pipeline_id, None)

    _run(_go())


def test_status_returns_none_for_unknown_pipeline(tmp_path):
    """未知 pipeline_id：与 P0-3 行为一致，返回 None。"""

    async def _go():
        sm, _engine = await _make_sessionmaker(tmp_path)
        async with sm() as db:
            assert await orch.get_pipeline_status("pl_does_not_exist", db=db) is None

    _run(_go())
