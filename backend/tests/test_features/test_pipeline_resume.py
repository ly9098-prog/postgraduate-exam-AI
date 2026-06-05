"""P2-5 manual resume — 单测。

覆盖：
- resume 后台任务只复跑 failed/pending chunk
- 老的 error_message 在 resume 后被清空
- 全部 chunk 成功后 pipeline 进入 completed
- 端点：404 / 409 / 重复上传 PDF 校验
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    async_sessionmaker,
    create_async_engine,
)

from app.core.database import Base
from app.features import pipeline_checkpoint as ckpt
from app.features.pipeline_orchestrator import (
    ImportPipeline,
    resume_pipeline_background,
)
from app.models.import_pipeline import ImportPipeline as ImportPipelineRow
from app.models.import_pipeline import ImportPipelineChunk


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


async def _make_session(tmp_path: Path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'p2_resume.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False), engine


def _run(coro):
    return asyncio.run(coro)


async def _seed_paused_pipeline(
    db,
    *,
    pipeline_id: str,
    chunks: list[tuple[int, int, int, str, str | None, str | None]],
    total_pages: int = 120,
) -> None:
    """Seed a pipeline with chunks=[(idx, page_start, page_end, status,
    batch_id, error_message), ...]."""
    db.add(
        ImportPipelineRow(
            pipeline_id=pipeline_id,
            source_type="pdf",
            source_file="x.pdf",
            total_pages=total_pages,
            chunk_size=40,
            status="paused",
        )
    )
    for idx, ps, pe, status, batch_id, err in chunks:
        db.add(
            ImportPipelineChunk(
                pipeline_id=pipeline_id,
                chunk_index=idx,
                page_start=ps,
                page_end=pe,
                status=status,
                batch_id=batch_id,
                question_count=0,
                error_message=err,
            )
        )
    await db.commit()


def _stub_pipeline_stages_for_resume(pipeline: ImportPipeline, written: int = 3):
    """Wire stages so resume's _execute_chunk → _run_single_pass returns a
    deterministic 'success' result without touching real PDF/AI."""
    pipeline._run_extract = MagicMock(
        return_value={"raw_blocks": [{"page": 1, "block_index": 0, "text": "x"}], "extracted": 1}
    )
    pipeline._run_normalize_text = MagicMock(
        return_value={"normalized_blocks": [
            {"page": 1, "block_index": 0, "raw_text": "x", "normalized_text": "x"}
        ]}
    )
    pipeline._run_split = MagicMock(return_value={"raw_questions": [], "split_count": written})
    pipeline._run_match = MagicMock(
        return_value={"matched": [], "unmatched": [], "matched_count": 0}
    )
    pipeline._run_normalize_schema = MagicMock(
        return_value={"questions": [], "normalized_count": written}
    )

    counter = {"n": 0}

    async def _fake_review(*args, **kwargs):
        counter["n"] += 1
        return {
            "batch_id": f"REVIEW_resume_{counter['n']}",
            "written": written,
            "skipped": 0,
            "total": written,
        }

    pipeline._run_review = AsyncMock(side_effect=_fake_review)


# ---------------------------------------------------------------------------
# resume_pipeline_background
# ---------------------------------------------------------------------------


class TestResumeOnlyFailedChunks:
    """3 个 chunk：0 completed / 1 failed / 2 completed → resume 只跑 chunk 1。"""

    def test_only_failed_chunk_replayed(self, tmp_path):
        async def _go():
            sm, _ = await _make_session(tmp_path)
            async with sm() as db:
                await _seed_paused_pipeline(
                    db,
                    pipeline_id="pl_resume_001",
                    chunks=[
                        (0, 1, 40, "completed", "REVIEW_old_0", None),
                        (1, 41, 80, "failed", None, "OCR exploded"),
                        (2, 81, 120, "completed", "REVIEW_old_2", None),
                    ],
                )

            # Patch ImportPipeline so the resume runner picks up our stubs.
            with patch(
                "app.features.pipeline_orchestrator.ImportPipeline",
            ) as PipelineCls:
                instance = ImportPipeline()
                instance.pipeline_id = "pl_resume_001"
                _stub_pipeline_stages_for_resume(instance, written=7)
                # Track which chunk_indices were executed.
                run_log: list[int] = []
                orig_exec = instance._execute_chunk

                async def _spy(**kwargs):
                    run_log.append(kwargs["chunk_index"])
                    return await orig_exec(**kwargs)

                instance._execute_chunk = _spy
                PipelineCls.return_value = instance

                async with sm() as db:
                    await resume_pipeline_background(
                        pipeline_id="pl_resume_001",
                        file_path="/tmp/fake_resume.pdf",
                        subject=None,
                        options={},
                        db=db,
                    )

                # Only chunk 1 should have been replayed.
                assert run_log == [1]

            # DB state: pipeline completed, all chunks completed, chunk 1
            # error cleared and got a fresh batch_id.
            async with sm() as db:
                progress = await ckpt.get_pipeline_progress(
                    db, "pl_resume_001", use_cache=False
                )
                assert progress["status"] == "completed"
                assert progress["completed_chunks"] == 3
                assert progress["failed_chunks"] == 0

                rows = (
                    (
                        await db.execute(
                            select(ImportPipelineChunk)
                            .where(
                                ImportPipelineChunk.pipeline_id == "pl_resume_001"
                            )
                            .order_by(ImportPipelineChunk.chunk_index)
                        )
                    )
                    .scalars()
                    .all()
                )
                # chunk 0 / 2 untouched
                assert rows[0].status == "completed"
                assert rows[0].batch_id == "REVIEW_old_0"
                assert rows[2].batch_id == "REVIEW_old_2"
                # chunk 1: error cleared, new batch_id, status completed
                assert rows[1].status == "completed"
                assert rows[1].error_message is None
                assert rows[1].batch_id and rows[1].batch_id.startswith("REVIEW_resume_")
                assert rows[1].question_count == 7

        _run(_go())


class TestResumeNoPendingChunks:
    """所有 chunk 都已 completed → resume 直接把 pipeline 标 completed。"""

    def test_no_pending_chunks_marks_completed(self, tmp_path):
        async def _go():
            sm, _ = await _make_session(tmp_path)
            async with sm() as db:
                await _seed_paused_pipeline(
                    db,
                    pipeline_id="pl_resume_done",
                    chunks=[
                        (0, 1, 40, "completed", "B0", None),
                        (1, 41, 80, "completed", "B1", None),
                    ],
                    total_pages=80,
                )

            async with sm() as db:
                await resume_pipeline_background(
                    pipeline_id="pl_resume_done",
                    file_path="/tmp/fake.pdf",
                    subject=None,
                    options={},
                    db=db,
                )

            async with sm() as db:
                progress = await ckpt.get_pipeline_progress(
                    db, "pl_resume_done", use_cache=False
                )
                assert progress["status"] == "completed"
                assert progress["finished_at"] is not None

        _run(_go())


class TestResumeStillFailing:
    """复跑后 chunk 仍失败 → pipeline 留在 paused，等下次 resume。"""

    def test_chunk_still_fails_keeps_paused(self, tmp_path):
        async def _go():
            sm, _ = await _make_session(tmp_path)
            async with sm() as db:
                await _seed_paused_pipeline(
                    db,
                    pipeline_id="pl_resume_stuck",
                    chunks=[
                        (0, 1, 40, "completed", "B0", None),
                        (1, 41, 80, "failed", None, "OCR exploded again"),
                    ],
                    total_pages=80,
                )

            with patch(
                "app.features.pipeline_orchestrator.ImportPipeline",
            ) as PipelineCls:
                instance = ImportPipeline()
                instance.pipeline_id = "pl_resume_stuck"
                _stub_pipeline_stages_for_resume(instance)
                # Make extract blow up to simulate a still-broken chunk.
                instance._run_extract = MagicMock(side_effect=RuntimeError("boom"))
                PipelineCls.return_value = instance

                async with sm() as db:
                    await resume_pipeline_background(
                        pipeline_id="pl_resume_stuck",
                        file_path="/tmp/fake.pdf",
                        subject=None,
                        options={},
                        db=db,
                    )

            async with sm() as db:
                progress = await ckpt.get_pipeline_progress(
                    db, "pl_resume_stuck", use_cache=False
                )
                assert progress["status"] == "paused"
                assert progress["failed_chunks"] == 1
                detail = progress["failed_chunk_details"][0]
                assert "boom" in detail["error_message"]

        _run(_go())


# ---------------------------------------------------------------------------
# endpoint validation (status + file checks)
# ---------------------------------------------------------------------------


class TestResumeEndpointValidation:
    """直接调 endpoint 函数验证 404 / 409 / 文件校验。"""

    def _make_upload_file(
        self, filename: str = "x.pdf", content: bytes = b"%PDF-1.4 fake"
    ):
        f = MagicMock()
        f.filename = filename
        f.content_type = "application/pdf"
        f.read = AsyncMock(return_value=content)
        return f

    def test_404_when_pipeline_missing(self, tmp_path):
        from app.api.v1.imports import resume_pipeline

        async def _go():
            sm, _ = await _make_session(tmp_path)
            async with sm() as db:
                user = MagicMock()
                with pytest.raises(Exception) as exc_info:
                    await resume_pipeline(
                        pipeline_id="pl_nope",
                        file=self._make_upload_file(),
                        db=db,
                        _=user,
                    )
                assert exc_info.value.status_code == 404

        _run(_go())

    def test_409_when_pipeline_completed(self, tmp_path):
        from app.api.v1.imports import resume_pipeline

        async def _go():
            sm, _ = await _make_session(tmp_path)
            async with sm() as db:
                db.add(
                    ImportPipelineRow(
                        pipeline_id="pl_done",
                        source_type="pdf",
                        source_file="x.pdf",
                        total_pages=40,
                        chunk_size=40,
                        status="completed",
                    )
                )
                await db.commit()
                user = MagicMock()
                with pytest.raises(Exception) as exc_info:
                    await resume_pipeline(
                        pipeline_id="pl_done",
                        file=self._make_upload_file(),
                        db=db,
                        _=user,
                    )
                assert exc_info.value.status_code == 409
                assert "completed" in exc_info.value.detail

        _run(_go())

    def test_400_when_non_pdf(self, tmp_path):
        from app.api.v1.imports import resume_pipeline

        async def _go():
            sm, _ = await _make_session(tmp_path)
            async with sm() as db:
                db.add(
                    ImportPipelineRow(
                        pipeline_id="pl_paused",
                        source_type="pdf",
                        source_file="x.pdf",
                        total_pages=40,
                        chunk_size=40,
                        status="paused",
                    )
                )
                await db.commit()
                user = MagicMock()
                with pytest.raises(Exception) as exc_info:
                    await resume_pipeline(
                        pipeline_id="pl_paused",
                        file=self._make_upload_file(filename="x.txt"),
                        db=db,
                        _=user,
                    )
                assert exc_info.value.status_code == 400

        _run(_go())
