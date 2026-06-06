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
                        current_user=user,
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
                        current_user=user,
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
                        current_user=user,
                    )
                assert exc_info.value.status_code == 400

        _run(_go())


# ---------------------------------------------------------------------------
# P0-1 / P0-2 security checks: creator ownership + uploaded file identity
# ---------------------------------------------------------------------------


class TestResumeSecurityChecks:
    """P0-1 / P0-2: resume endpoint 必须校验创建者 + 文件字节摘要，
    历史 paused pipeline（NULL 字段）保持向后兼容。"""

    def _make_upload_file(
        self, filename: str = "x.pdf", content: bytes = b"%PDF-1.4 fake"
    ):
        f = MagicMock()
        f.filename = filename
        f.content_type = "application/pdf"
        f.read = AsyncMock(return_value=content)
        return f

    def _make_user(self, user_id):
        u = MagicMock()
        u.id = user_id
        return u

    async def _seed_pipeline(
        self,
        db,
        *,
        pipeline_id: str,
        created_by: str | None,
        source_sha256: str | None,
        total_pages: int = 40,
        status: str = "paused",
    ):
        db.add(
            ImportPipelineRow(
                pipeline_id=pipeline_id,
                source_type="pdf",
                source_file="x.pdf",
                total_pages=total_pages,
                chunk_size=40,
                status=status,
                created_by=created_by,
                source_sha256=source_sha256,
            )
        )
        await db.commit()

    def test_resume_403_when_user_is_not_creator(self, tmp_path):
        """pipeline.created_by="user_a" + 请求者 user_b → 403。"""
        from app.api.v1.imports import resume_pipeline

        async def _go():
            sm, _ = await _make_session(tmp_path)
            async with sm() as db:
                await self._seed_pipeline(
                    db,
                    pipeline_id="pl_owner_001",
                    created_by="user_a",
                    source_sha256="0" * 64,
                )
                user_b = self._make_user("user_b")
                with pytest.raises(Exception) as exc_info:
                    await resume_pipeline(
                        pipeline_id="pl_owner_001",
                        file=self._make_upload_file(),
                        db=db,
                        current_user=user_b,
                    )
                assert exc_info.value.status_code == 403
                assert "creator" in exc_info.value.detail

        _run(_go())

    def test_resume_400_when_sha256_mismatch(self, tmp_path):
        """pipeline.source_sha256 与上传 hash 不一致 → 400。"""
        import hashlib as _hashlib

        from app.api.v1.imports import resume_pipeline

        async def _go():
            sm, _ = await _make_session(tmp_path)
            async with sm() as db:
                # source_sha256 records "old.pdf", upload sends "new.pdf".
                old_hash = _hashlib.sha256(b"old pdf bytes").hexdigest()
                await self._seed_pipeline(
                    db,
                    pipeline_id="pl_hash_001",
                    created_by="user_a",
                    source_sha256=old_hash,
                )

                # Build a real PDF that pdf parser accepts (page count 40).
                # We do not actually need fitz to succeed; if it raises 400 PDF
                # parse failure first, the test would mask the sha mismatch
                # signal. Patch fitz.open to a 40-page doc.
                fake_doc = MagicMock()
                fake_doc.__enter__ = MagicMock(return_value=fake_doc)
                fake_doc.__exit__ = MagicMock(return_value=False)
                fake_doc.__len__ = MagicMock(return_value=40)
                with patch("fitz.open", return_value=fake_doc):
                    user_a = self._make_user("user_a")
                    with pytest.raises(Exception) as exc_info:
                        await resume_pipeline(
                            pipeline_id="pl_hash_001",
                            file=self._make_upload_file(
                                content=b"new pdf bytes"
                            ),
                            db=db,
                            current_user=user_a,
                        )
                    assert exc_info.value.status_code == 400
                    assert "match" in exc_info.value.detail

        _run(_go())

    def test_resume_legacy_pipeline_without_created_by_allowed(self, tmp_path):
        """created_by IS NULL（历史数据）→ 任意 import:write 用户均可 resume。"""
        from app.api.v1.imports import resume_pipeline
        from app.schemas.import_review import PipelineResumeResponse

        async def _go():
            sm, _ = await _make_session(tmp_path)
            async with sm() as db:
                # Legacy pipeline: both fields NULL. No pending chunks → endpoint
                # short-circuits before background dispatch (avoids needing to
                # patch asyncio.create_task / fitz).
                await self._seed_pipeline(
                    db,
                    pipeline_id="pl_legacy_owner",
                    created_by=None,
                    source_sha256=None,
                )

                fake_doc = MagicMock()
                fake_doc.__enter__ = MagicMock(return_value=fake_doc)
                fake_doc.__exit__ = MagicMock(return_value=False)
                fake_doc.__len__ = MagicMock(return_value=40)
                with patch("fitz.open", return_value=fake_doc):
                    user_x = self._make_user("user_x")
                    response = await resume_pipeline(
                        pipeline_id="pl_legacy_owner",
                        file=self._make_upload_file(),
                        db=db,
                        current_user=user_x,
                    )
                    assert isinstance(response, PipelineResumeResponse)
                    assert response.pipeline_id == "pl_legacy_owner"
                    # No chunks → resumed_chunks empty, status echoes paused.
                    assert response.resumed_chunks == []

        _run(_go())

    def test_resume_legacy_pipeline_without_sha256_allowed(self, tmp_path):
        """source_sha256 IS NULL（历史数据）→ 跳过字节级校验，按页数继续。"""
        from app.api.v1.imports import resume_pipeline
        from app.schemas.import_review import PipelineResumeResponse

        async def _go():
            sm, _ = await _make_session(tmp_path)
            async with sm() as db:
                # Legacy: created_by set, source_sha256 NULL.
                await self._seed_pipeline(
                    db,
                    pipeline_id="pl_legacy_hash",
                    created_by="user_a",
                    source_sha256=None,
                )

                fake_doc = MagicMock()
                fake_doc.__enter__ = MagicMock(return_value=fake_doc)
                fake_doc.__exit__ = MagicMock(return_value=False)
                fake_doc.__len__ = MagicMock(return_value=40)
                with patch("fitz.open", return_value=fake_doc):
                    user_a = self._make_user("user_a")
                    response = await resume_pipeline(
                        pipeline_id="pl_legacy_hash",
                        file=self._make_upload_file(
                            content=b"any pdf bytes accepted"
                        ),
                        db=db,
                        current_user=user_a,
                    )
                    assert isinstance(response, PipelineResumeResponse)
                    assert response.pipeline_id == "pl_legacy_hash"
                    assert response.resumed_chunks == []

        _run(_go())


# ---------------------------------------------------------------------------
# P0-3 watermark snapshot
# ---------------------------------------------------------------------------


class TestResumeWatermarkSnapshot:
    """P0-3: resume 时优先用 pipeline_row.watermark_snapshot；NULL 才回退到
    watermark service 实时加载。"""

    async def _seed_with_snapshot(
        self,
        db,
        *,
        pipeline_id: str,
        watermark_snapshot,
    ) -> None:
        db.add(
            ImportPipelineRow(
                pipeline_id=pipeline_id,
                source_type="pdf",
                source_file="x.pdf",
                total_pages=80,
                chunk_size=40,
                status="paused",
                watermark_snapshot=watermark_snapshot,
            )
        )
        # 一个 failed chunk 触发 resume 实际跑 _execute_chunk
        db.add(
            ImportPipelineChunk(
                pipeline_id=pipeline_id,
                chunk_index=0,
                page_start=1,
                page_end=40,
                status="completed",
                batch_id="REVIEW_old_0",
                question_count=0,
            )
        )
        db.add(
            ImportPipelineChunk(
                pipeline_id=pipeline_id,
                chunk_index=1,
                page_start=41,
                page_end=80,
                status="failed",
                batch_id=None,
                question_count=0,
                error_message="prior failure",
            )
        )
        await db.commit()

    def test_resume_uses_watermark_snapshot_when_present(self, tmp_path):
        """snapshot=[{"pattern":"FOO_SNAPSHOT"}] + load_rules 返回不同
        patterns → resume 用 snapshot patterns，不调 load_rules。"""

        async def _go():
            sm, _ = await _make_session(tmp_path)
            async with sm() as db:
                await self._seed_with_snapshot(
                    db,
                    pipeline_id="pl_wm_snap_001",
                    watermark_snapshot=[{"pattern": r"FOO_SNAPSHOT", "flags": 0}],
                )

            captured: dict = {"watermarks": None}

            with patch(
                "app.features.pipeline_orchestrator.ImportPipeline",
            ) as PipelineCls:
                instance = ImportPipeline()
                instance.pipeline_id = "pl_wm_snap_001"
                _stub_pipeline_stages_for_resume(instance, written=2)

                # 拦截 normalize_text，记录 chunk 实际收到的 watermark_patterns
                def _capture(raw_blocks, **kw):
                    captured["watermarks"] = kw.get("watermark_patterns")
                    return {"normalized_blocks": [
                        {"page": 1, "block_index": 0, "raw_text": "x", "normalized_text": "x"}
                    ]}

                instance._run_normalize_text = MagicMock(side_effect=_capture)
                PipelineCls.return_value = instance

                # 实时 load_rules 应永不被调用——若被调用，断言会失败
                load_rules_called = {"n": 0}

                async def _fake_load_rules(_db):
                    load_rules_called["n"] += 1
                    import re as _re
                    return [_re.compile(r"DRIFTED_RULE")]

                with patch(
                    "app.services.watermark_service.load_rules",
                    side_effect=_fake_load_rules,
                ):
                    async with sm() as db:
                        await resume_pipeline_background(
                            pipeline_id="pl_wm_snap_001",
                            file_path="/tmp/fake_resume.pdf",
                            subject=None,
                            options={},
                            db=db,
                        )

                # 断言 chunk 真用了 snapshot 的 patterns（FOO_SNAPSHOT），
                # 而不是 live 的 DRIFTED_RULE
                assert captured["watermarks"] is not None
                assert len(captured["watermarks"]) == 1
                assert captured["watermarks"][0].pattern == r"FOO_SNAPSHOT"
                # 没调过 load_rules
                assert load_rules_called["n"] == 0

        _run(_go())

    def test_resume_legacy_no_snapshot_falls_back_to_load(self, tmp_path, caplog):
        """snapshot=None（历史 pipeline）→ resume 走 watermark service 加载
        路径并打 warning 日志。"""

        async def _go():
            sm, _ = await _make_session(tmp_path)
            async with sm() as db:
                await self._seed_with_snapshot(
                    db,
                    pipeline_id="pl_wm_legacy_001",
                    watermark_snapshot=None,
                )

            with patch(
                "app.features.pipeline_orchestrator.ImportPipeline",
            ) as PipelineCls:
                instance = ImportPipeline()
                instance.pipeline_id = "pl_wm_legacy_001"
                _stub_pipeline_stages_for_resume(instance, written=1)
                PipelineCls.return_value = instance

                load_rules_called = {"n": 0}

                async def _fake_load_rules(_db):
                    load_rules_called["n"] += 1
                    import re as _re
                    return [_re.compile(r"LIVE_RULE")]

                import logging
                with caplog.at_level(logging.WARNING):
                    with patch(
                        "app.services.watermark_service.load_rules",
                        side_effect=_fake_load_rules,
                    ):
                        async with sm() as db:
                            await resume_pipeline_background(
                                pipeline_id="pl_wm_legacy_001",
                                file_path="/tmp/fake_resume.pdf",
                                subject=None,
                                options={},
                                db=db,
                            )

                # snapshot=NULL → 必须 fallback 到 load_rules
                assert load_rules_called["n"] == 1
                # 至少打一条 warning（task spec：内容不强求）
                assert any(
                    record.levelno == logging.WARNING
                    and "pl_wm_legacy_001" in record.getMessage()
                    for record in caplog.records
                )

        _run(_go())

