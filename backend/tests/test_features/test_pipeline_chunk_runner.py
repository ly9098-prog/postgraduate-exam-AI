"""P2-2 chunk runner + 失败隔离 单测。

覆盖范围：
- 多 chunk happy path（DB checkpoint 写入完整）
- 单 chunk 失败隔离（pipeline.status=paused，其它 chunk 仍 completed）
- chunk_size 由 env 覆盖
- 没题的 chunk 标 completed（不是 failed）
- 分块辅助函数：_split_into_chunks / _resolve_chunk_size

backward-compat：单 chunk / txt / 短 PDF 走 legacy single-pass，
test_pipeline_orchestrator 已覆盖。
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.database import Base
# Import all models to ensure Base.metadata has FK targets
import app.models.user  # noqa: F401 — users table for FKs
import app.models.formula  # noqa: F401 — formula tables for FKs
from app.features import pipeline_checkpoint as ckpt
from app.features.pipeline_orchestrator import (
    ImportPipeline,
    _resolve_chunk_size,
    _split_into_chunks,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


async def _make_session(tmp_path: Path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'p2_chunk.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False), engine


def _run(coro):
    return asyncio.run(coro)


def _make_render_result(page_count: int):
    """Return a PdfRenderResult with *page_count* pages of fake PNG data."""
    from app.services.pdf_renderer_service import PdfRenderResult
    return PdfRenderResult(
        page_images={i: b"fake_png_bytes" for i in range(1, page_count + 1)},
        rendered_count=page_count,
        total_pages=page_count,
    )


def _mock_render_pages(page_count: int):
    """Patch ``pdf_renderer.render_pages`` to return a result with *page_count* pages."""
    return patch(
        "app.services.pdf_renderer_service.pdf_renderer.render_pages",
        return_value=_make_render_result(page_count),
    )


def _stub_pdf_doc(total_pages: int):
    """Return a fitz-style mock doc supporting len() and close()."""
    doc = MagicMock()
    doc.__len__ = MagicMock(return_value=total_pages)
    doc.close = MagicMock()
    return doc


def _stub_pipeline_stages(pipeline: ImportPipeline, *, written_per_chunk: int = 5):
    """Wire every async/sync stage to a deterministic stub.

    Each chunk's run_single_pass returns a "fake batch" with `written` review
    items so we can assert per-chunk batch_id propagation.
    """
    pipeline._run_extract = MagicMock(
        return_value={"raw_blocks": [{"page": 1, "block_index": 0, "text": "x"}], "extracted": 1}
    )
    pipeline._run_normalize_text = MagicMock(
        return_value={"normalized_blocks": [
            {"page": 1, "block_index": 0, "raw_text": "x", "normalized_text": "x"}
        ]}
    )
    pipeline._run_split = MagicMock(return_value={"raw_questions": [], "split_count": written_per_chunk})
    pipeline._run_match = MagicMock(
        return_value={"matched": [], "unmatched": [], "matched_count": 0}
    )
    pipeline._run_normalize_schema = MagicMock(
        return_value={"questions": [], "normalized_count": written_per_chunk}
    )

    counter = {"n": 0}

    async def _fake_review(*args, **kwargs):
        counter["n"] += 1
        return {
            "batch_id": f"REVIEW_chunk_{counter['n']}",
            "written": written_per_chunk,
            "skipped": 0,
            "total": written_per_chunk,
        }

    pipeline._run_review = AsyncMock(side_effect=_fake_review)
    return pipeline


# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------


class TestSplitIntoChunks:
    def test_evenly_divisible(self):
        assert _split_into_chunks(120, 40) == [(1, 40), (41, 80), (81, 120)]

    def test_remainder_chunk(self):
        assert _split_into_chunks(100, 40) == [(1, 40), (41, 80), (81, 100)]

    def test_single_chunk_when_total_le_size(self):
        assert _split_into_chunks(40, 40) == [(1, 40)]
        assert _split_into_chunks(10, 40) == [(1, 10)]

    def test_zero_or_negative_input(self):
        assert _split_into_chunks(0, 40) == []
        assert _split_into_chunks(100, 0) == []


class TestResolveChunkSize:
    def test_default_when_unset(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("IMPORT_PIPELINE_CHUNK_SIZE", None)
            assert _resolve_chunk_size() == 40

    def test_env_override(self):
        with patch.dict(os.environ, {"IMPORT_PIPELINE_CHUNK_SIZE": "20"}):
            assert _resolve_chunk_size() == 20

    def test_invalid_env_falls_back_to_default(self):
        with patch.dict(os.environ, {"IMPORT_PIPELINE_CHUNK_SIZE": "abc"}):
            assert _resolve_chunk_size() == 40


# ---------------------------------------------------------------------------
# chunked run path
# ---------------------------------------------------------------------------


class TestChunkedRunHappyPath:
    """120 页 / chunk_size=40 → 3 chunks 全部 completed。"""

    def test_all_chunks_completed_pipeline_completed(self, tmp_path):
        async def _go():
            sm, _ = await _make_session(tmp_path)
            async with sm() as db:
                pipeline = ImportPipeline()
                pipeline.pipeline_id = "pl_chunked_001"
                _stub_pipeline_stages(pipeline, written_per_chunk=7)

                # _plan_chunks reads PDF page count; stub it
                with patch.dict(os.environ, {"IMPORT_PIPELINE_CHUNK_SIZE": "40"}):
                    with patch(
                        "app.features.pipeline_orchestrator._read_pdf_page_count",
                        return_value=120,
                    ):
                        with _mock_render_pages(120):
                            result = await pipeline.run(
                                file_path="/tmp/fake.pdf",
                                source_type="pdf",
                                source_file="王道.pdf",
                                db=db,
                            )

                assert result["status"] == "completed"
                assert result["stats"]["total_chunks"] == 3
                assert result["stats"]["completed_chunks"] == 3
                assert result["stats"]["failed_chunks"] == 0
                assert result["stats"]["to_review"] == 21  # 7 * 3
                # each chunk got its own batch_id
                batch_ids = [c["batch_id"] for c in result["diagnostics"]["chunks"]]
                assert len(set(batch_ids)) == 3
                assert all(b is not None for b in batch_ids)

            # DB state: 1 pipeline row + 3 chunk rows, all completed
            async with sm() as db:
                progress = await ckpt.get_pipeline_progress(
                    db, "pl_chunked_001", use_cache=False
                )
                assert progress["status"] == "completed"
                assert progress["total_chunks"] == 3
                assert progress["completed_chunks"] == 3
                assert progress["failed_chunks"] == 0
                assert progress["question_count"] == 21
                assert progress["finished_at"] is not None

        _run(_go())


class TestChunkFailureIsolation:
    """Chunk 1 抛错时：chunk 0/2 仍 completed，pipeline.status=paused。"""

    def test_single_chunk_failure_does_not_kill_pipeline(self, tmp_path):
        async def _go():
            sm, _ = await _make_session(tmp_path)
            async with sm() as db:
                pipeline = ImportPipeline()
                pipeline.pipeline_id = "pl_isolate_001"
                _stub_pipeline_stages(pipeline, written_per_chunk=4)

                # mock extract: chunk 0 (pages 1-40) ok, chunk 1 (41-80) fail,
                # chunk 2 (81-120) ok again
                call_log = []

                def _extract_side(file_content=None, source_type="pdf", file_path=None, **kw):
                    opts = kw.get("options") or {}
                    page_start = opts.get("page_start")
                    call_log.append(page_start)
                    if page_start == 41:
                        raise RuntimeError("OCR exploded mid-chunk")
                    return {
                        "raw_blocks": [{"page": page_start, "block_index": 0, "text": "x"}],
                        "extracted": 1,
                    }

                pipeline._run_extract = MagicMock(side_effect=_extract_side)

                with patch.dict(os.environ, {"IMPORT_PIPELINE_CHUNK_SIZE": "40"}):
                    with patch(
                        "app.features.pipeline_orchestrator._read_pdf_page_count",
                        return_value=120,
                    ):
                        with _mock_render_pages(120):
                            result = await pipeline.run(
                                file_path="/tmp/fake.pdf",
                                source_type="pdf",
                                source_file="x.pdf",
                                db=db,
                            )

                assert result["status"] == "paused"
                assert result["stats"]["completed_chunks"] == 2
                assert result["stats"]["failed_chunks"] == 1
                # 失败 chunk 没有 batch_id；其余 chunks 有
                chunks = result["diagnostics"]["chunks"]
                assert chunks[0]["status"] == "completed"
                assert chunks[1]["status"] == "failed"
                assert "OCR exploded" in chunks[1]["error_message"]
                assert chunks[2]["status"] == "completed"
                # 调用了三次 extract，page_start 分别是 1/41/81
                assert call_log == [1, 41, 81]

            # DB checkpoint：失败 chunk 单独标记 failed，其余 completed
            async with sm() as db:
                progress = await ckpt.get_pipeline_progress(
                    db, "pl_isolate_001", use_cache=False
                )
                assert progress["status"] == "paused"
                assert progress["completed_chunks"] == 2
                assert progress["failed_chunks"] == 1
                assert len(progress["failed_chunk_details"]) == 1
                detail = progress["failed_chunk_details"][0]
                assert detail["chunk_index"] == 1
                assert detail["page_start"] == 41
                assert detail["page_end"] == 80
                assert "OCR exploded" in detail["error_message"]

        _run(_go())


class TestChunkSizeFromEnv:
    """IMPORT_PIPELINE_CHUNK_SIZE 应该影响实际切分粒度。"""

    def test_smaller_chunk_size_creates_more_chunks(self, tmp_path):
        async def _go():
            sm, _ = await _make_session(tmp_path)
            async with sm() as db:
                pipeline = ImportPipeline()
                pipeline.pipeline_id = "pl_envchunk_001"
                _stub_pipeline_stages(pipeline, written_per_chunk=1)

                with patch.dict(os.environ, {"IMPORT_PIPELINE_CHUNK_SIZE": "20"}):
                    with patch(
                        "app.features.pipeline_orchestrator._read_pdf_page_count",
                        return_value=100,
                    ):
                        with _mock_render_pages(100):
                            result = await pipeline.run(
                                file_path="/tmp/fake.pdf",
                                source_type="pdf",
                                source_file="x.pdf",
                                db=db,
                            )

                assert result["stats"]["total_chunks"] == 5  # 100 / 20
                # check chunk_ranges via diagnostics
                ranges = [(c["page_start"], c["page_end"]) for c in result["diagnostics"]["chunks"]]
                assert ranges == [(1, 20), (21, 40), (41, 60), (61, 80), (81, 100)]

        _run(_go())


class TestEmptyChunkStillCompleted:
    """OCR 出 0 题的 chunk 应该 status=completed，question_count=0。"""

    def test_empty_chunk_marked_completed_not_failed(self, tmp_path):
        async def _go():
            sm, _ = await _make_session(tmp_path)
            async with sm() as db:
                pipeline = ImportPipeline()
                pipeline.pipeline_id = "pl_empty_001"
                _stub_pipeline_stages(pipeline, written_per_chunk=0)

                with patch.dict(os.environ, {"IMPORT_PIPELINE_CHUNK_SIZE": "40"}):
                    with patch(
                        "app.features.pipeline_orchestrator._read_pdf_page_count",
                        return_value=80,
                    ):
                        with _mock_render_pages(80):
                            result = await pipeline.run(
                            file_path="/tmp/fake.pdf",
                            source_type="pdf",
                            source_file="x.pdf",
                            db=db,
                        )

                assert result["status"] == "completed"
                assert result["stats"]["completed_chunks"] == 2
                assert result["stats"]["failed_chunks"] == 0
                assert result["stats"]["to_review"] == 0

        _run(_go())


# ---------------------------------------------------------------------------
# backward-compat: single-pass branch still kicks in
# ---------------------------------------------------------------------------


class TestSinglePassFallback:
    """以下场景应继续走 legacy single-pass，不创建 import_pipelines 行。"""

    def test_txt_source_does_not_chunk(self, tmp_path):
        async def _go():
            sm, _ = await _make_session(tmp_path)
            async with sm() as db:
                pipeline = ImportPipeline()
                pipeline.pipeline_id = "pl_txt_001"
                _stub_pipeline_stages(pipeline, written_per_chunk=2)

                # txt 永远不读 PDF page count，也不应进入 chunked branch
                with patch(
                    "app.features.pipeline_orchestrator._read_pdf_page_count",
                    side_effect=AssertionError("should not be called for txt"),
                ):
                    result = await pipeline.run(
                        file_content=b"some text",
                        source_type="txt",
                        source_file="notes.txt",
                        db=db,
                    )

                # 走 legacy 分支：stats 是 single-pass 形态（含 schema_normalized）
                assert "schema_normalized" in result["stats"]
                assert "total_chunks" not in result["stats"]
                # 没有创建 import_pipelines 行
                progress = await ckpt.get_pipeline_progress(
                    db, "pl_txt_001", use_cache=False
                )
                assert progress is None

        _run(_go())

    def test_pdf_with_user_page_range_does_not_chunk(self, tmp_path):
        """用户指定 page_start/page_end 时绕过自动分块。"""
        async def _go():
            sm, _ = await _make_session(tmp_path)
            async with sm() as db:
                pipeline = ImportPipeline()
                pipeline.pipeline_id = "pl_userrange_001"
                _stub_pipeline_stages(pipeline, written_per_chunk=2)

                with patch(
                    "app.features.pipeline_orchestrator._read_pdf_page_count",
                    side_effect=AssertionError("should not be called when user pinned range"),
                ):
                    with _mock_render_pages(50):
                        result = await pipeline.run(
                            file_path="/tmp/fake.pdf",
                            source_type="pdf",
                            source_file="x.pdf",
                            db=db,
                            options={"page_start": 10, "page_end": 50},
                        )

                assert "total_chunks" not in result["stats"]
                progress = await ckpt.get_pipeline_progress(
                    db, "pl_userrange_001", use_cache=False
                )
                assert progress is None

        _run(_go())

    def test_short_pdf_does_not_chunk(self, tmp_path):
        """页数 ≤ chunk_size 时退化成 single-pass，不写 checkpoint。"""
        async def _go():
            sm, _ = await _make_session(tmp_path)
            async with sm() as db:
                pipeline = ImportPipeline()
                pipeline.pipeline_id = "pl_short_001"
                _stub_pipeline_stages(pipeline, written_per_chunk=1)

                with patch.dict(os.environ, {"IMPORT_PIPELINE_CHUNK_SIZE": "40"}):
                    with patch(
                        "app.features.pipeline_orchestrator._read_pdf_page_count",
                        return_value=20,  # < chunk_size
                    ):
                        with _mock_render_pages(20):
                            result = await pipeline.run(
                                file_path="/tmp/fake.pdf",
                                source_type="pdf",
                                source_file="x.pdf",
                                db=db,
                            )

                assert "total_chunks" not in result["stats"]
                progress = await ckpt.get_pipeline_progress(
                    db, "pl_short_001", use_cache=False
                )
                assert progress is None

        _run(_go())

    def test_no_db_does_not_chunk(self):
        """无 db session 时（image OCR 间接路径等）也不分块。"""
        async def _go():
            pipeline = ImportPipeline()
            pipeline.pipeline_id = "pl_nodb_001"
            _stub_pipeline_stages(pipeline, written_per_chunk=0)

            with patch(
                "app.features.pipeline_orchestrator._read_pdf_page_count",
                side_effect=AssertionError("should not chunk without db"),
            ):
                with _mock_render_pages(1):
                    result = await pipeline.run(
                        file_path="/tmp/fake.pdf",
                        source_type="pdf",
                        source_file="x.pdf",
                        db=None,
                    )

            assert "total_chunks" not in result["stats"]

        _run(_go())


# ---------------------------------------------------------------------------
# P2-3 边界对齐 ±3 页
# ---------------------------------------------------------------------------


class TestResolveChunkOverlap:
    def test_default_when_unset(self):
        from app.features.pipeline_orchestrator import _resolve_chunk_overlap
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("IMPORT_PIPELINE_CHUNK_OVERLAP", None)
            assert _resolve_chunk_overlap() == 3

    def test_env_override(self):
        from app.features.pipeline_orchestrator import _resolve_chunk_overlap
        with patch.dict(os.environ, {"IMPORT_PIPELINE_CHUNK_OVERLAP": "5"}):
            assert _resolve_chunk_overlap() == 5

    def test_zero_disables_overlap(self):
        from app.features.pipeline_orchestrator import _resolve_chunk_overlap
        with patch.dict(os.environ, {"IMPORT_PIPELINE_CHUNK_OVERLAP": "0"}):
            assert _resolve_chunk_overlap() == 0

    def test_invalid_falls_back_to_default(self):
        from app.features.pipeline_orchestrator import _resolve_chunk_overlap
        with patch.dict(os.environ, {"IMPORT_PIPELINE_CHUNK_OVERLAP": "abc"}):
            assert _resolve_chunk_overlap() == 3

    def test_negative_clamped_to_zero(self):
        from app.features.pipeline_orchestrator import _resolve_chunk_overlap
        with patch.dict(os.environ, {"IMPORT_PIPELINE_CHUNK_OVERLAP": "-5"}):
            assert _resolve_chunk_overlap() == 0


class TestSplitOverlapDedup:
    """直接调 _run_split，验证 chunk overlap 去重 + boundary 警告逻辑。"""

    def test_overlap_zone_dedup_drops_duplicates(self):
        """P1-3: seen_hashes 已含的 hash，且 page_start > logical_end 的会被丢弃。

        keying 改用 question_hash 而非 OCR 题号——题号在 OCR 抖动下不稳定。
        """
        from app.features.pipeline_orchestrator import _compute_overlap_hash

        pipeline = ImportPipeline()

        dup_q = {
            "number": 41, "page_start": 42, "page_end": 42,
            "raw_question_text": "Q41 stem", "has_options": True,
            "option_lines": {"A": "a", "B": "b", "C": "c", "D": "d"},
        }
        dup_hash = _compute_overlap_hash(dup_q)
        assert dup_hash, "fixture should produce a non-empty hash"

        # 模拟 split_questions 直接返回 3 题
        fake_questions = [
            {"number": 39, "page_start": 38, "page_end": 39, "raw_question_text": "Q39",
             "has_options": True, "option_lines": {"A": "a", "B": "b", "C": "c", "D": "d"}},
            {"number": 40, "page_start": 40, "page_end": 41, "raw_question_text": "Q40",
             "has_options": True, "option_lines": {"A": "a", "B": "b", "C": "c", "D": "d"}},
            # 第 41 题在 overlap 区（page_start=42 > logical_end=40），且
            # 上一个 chunk 已写过同一 hash，应被丢
            dup_q,
        ]

        seen_hashes = {dup_hash}
        with patch(
            "app.features.pipeline_orchestrator.split_questions",
            return_value=fake_questions,
        ):
            result = pipeline._run_split(
                normalized_blocks=[
                    {"page": 38, "block_index": 0, "normalized_text": "x", "raw_text": "x"},
                ],
                _chunk_seen_hashes=seen_hashes,
                _chunk_logical_end=40,
            )

        kept_numbers = [q["number"] for q in result["raw_questions"]]
        assert kept_numbers == [39, 40]
        assert 41 not in kept_numbers
        # seen_hashes 累加被保留题目的 hash
        assert _compute_overlap_hash(fake_questions[0]) in seen_hashes
        assert _compute_overlap_hash(fake_questions[1]) in seen_hashes
        # warning + diagnostics 记录跳过项（按题号汇报，便于人工查阅）
        assert any("boundary_overlap_skipped" in w for w in result["warnings"])
        assert result["split_diagnostics"]["overlap_skipped_numbers"] == [41]

    def test_first_sighting_in_overlap_zone_is_kept(self):
        """page_start 在 overlap 区，但 seen_hashes 不包含该 hash → 保留。"""
        pipeline = ImportPipeline()
        fake_questions = [
            {"number": 42, "page_start": 42, "page_end": 42, "raw_question_text": "Q42",
             "has_options": True, "option_lines": {"A": "a", "B": "b", "C": "c", "D": "d"}},
        ]
        seen_hashes: set = set()
        with patch(
            "app.features.pipeline_orchestrator.split_questions",
            return_value=fake_questions,
        ):
            result = pipeline._run_split(
                normalized_blocks=[{"page": 42, "block_index": 0, "normalized_text": "x", "raw_text": "x"}],
                _chunk_seen_hashes=seen_hashes,
                _chunk_logical_end=40,
            )
        assert [q["number"] for q in result["raw_questions"]] == [42]
        assert len(seen_hashes) == 1

    def test_duplicate_inside_logical_range_kept(self):
        """seen_hashes 含某 hash 但 page_start ≤ logical_end → 保留，避免误删合法重号。"""
        from app.features.pipeline_orchestrator import _compute_overlap_hash

        pipeline = ImportPipeline()
        q = {
            "number": 41, "page_start": 39, "page_end": 39,
            "raw_question_text": "Q41", "has_options": True,
            "option_lines": {"A": "a", "B": "b", "C": "c", "D": "d"},
        }
        seen_hashes = {_compute_overlap_hash(q)}
        with patch(
            "app.features.pipeline_orchestrator.split_questions",
            return_value=[q],
        ):
            result = pipeline._run_split(
                normalized_blocks=[{"page": 39, "block_index": 0, "normalized_text": "x", "raw_text": "x"}],
                _chunk_seen_hashes=seen_hashes,
                _chunk_logical_end=40,
            )
        # 41 在 page 39（< logical_end=40），不算 overlap，保留
        assert [q["number"] for q in result["raw_questions"]] == [41]

    def test_overlap_dedup_robust_to_ocr_number_jitter(self):
        """P1-3: 同一物理题在两个 chunk 的 OCR 题号不一致（如 41/I）也能命中去重。

        老逻辑用 ``number`` 当 key——OCR 把 ``41`` 识成 ``I/l/4l`` 时漏掉
        重复项。新逻辑用 stem+option 的 hash，hash 与 number 无关，因此
        无论上一个 chunk 写入的题号是多少，只要题干和选项一致，第二个
        chunk 的 overlap 区就能正确丢弃。
        """
        from app.features.pipeline_orchestrator import _compute_overlap_hash

        pipeline = ImportPipeline()
        prev_chunk_q = {
            "number": 41, "page_start": 39, "page_end": 40,
            "raw_question_text": "下列哪个是质数",
            "has_options": True,
            "option_lines": {"A": "4", "B": "6", "C": "7", "D": "9"},
        }
        # OCR 在第二个 chunk 把 41 误识成别的
        jittered_q = {**prev_chunk_q, "number": 999, "page_start": 42, "page_end": 42}

        seen_hashes = {_compute_overlap_hash(prev_chunk_q)}
        with patch(
            "app.features.pipeline_orchestrator.split_questions",
            return_value=[jittered_q],
        ):
            result = pipeline._run_split(
                normalized_blocks=[
                    {"page": 42, "block_index": 0, "normalized_text": "x", "raw_text": "x"},
                ],
                _chunk_seen_hashes=seen_hashes,
                _chunk_logical_end=40,
            )

        # 题号变了但 hash 没变 → 仍被识别为 overlap 重复
        assert result["raw_questions"] == []
        assert any("boundary_overlap_skipped" in w for w in result["warnings"])

    def test_overlap_dedup_does_not_drop_section_reset_numbers(self):
        """P1-3: 同一文档里题号重置（一卷 1-50、二卷 1-50）不再误删。

        老逻辑只看 number，第二卷的题 1 在 overlap 区会被当成重复丢弃。
        新逻辑用 stem+option 的 hash，题干不同 → hash 不同 → 保留。
        """
        from app.features.pipeline_orchestrator import _compute_overlap_hash

        pipeline = ImportPipeline()
        prev_q = {
            "number": 1, "page_start": 1, "page_end": 1,
            "raw_question_text": "数学一卷 第一题",
            "has_options": True,
            "option_lines": {"A": "a", "B": "b", "C": "c", "D": "d"},
        }
        new_section_q = {
            "number": 1, "page_start": 42, "page_end": 42,
            "raw_question_text": "英语二卷 第一题",
            "has_options": True,
            "option_lines": {"A": "x", "B": "y", "C": "z", "D": "w"},
        }
        seen_hashes = {_compute_overlap_hash(prev_q)}
        with patch(
            "app.features.pipeline_orchestrator.split_questions",
            return_value=[new_section_q],
        ):
            result = pipeline._run_split(
                normalized_blocks=[{"page": 42, "block_index": 0, "normalized_text": "x", "raw_text": "x"}],
                _chunk_seen_hashes=seen_hashes,
                _chunk_logical_end=40,
            )
        assert [q["number"] for q in result["raw_questions"]] == [1]
        assert not any("boundary_overlap_skipped" in w for w in result["warnings"])

    def test_boundary_unclosed_warning_emitted(self):
        """末题落在 logical_end 附近且选项缺 D/E → emit chunk_boundary_unclosed。"""
        pipeline = ImportPipeline()
        fake_questions = [
            # 末题 page_end=40 == logical_end，options 只有 A/B/C → 触发警告
            {"number": 50, "page_start": 39, "page_end": 40, "raw_question_text": "Q50",
             "has_options": True, "option_lines": {"A": "a", "B": "b", "C": "c"}},
        ]
        seen_hashes: set = set()
        with patch(
            "app.features.pipeline_orchestrator.split_questions",
            return_value=fake_questions,
        ):
            result = pipeline._run_split(
                normalized_blocks=[{"page": 40, "block_index": 0, "normalized_text": "x", "raw_text": "x"}],
                _chunk_seen_hashes=seen_hashes,
                _chunk_logical_end=40,
            )
        assert any("chunk_boundary_unclosed" in w for w in result["warnings"])
        assert result["split_diagnostics"]["boundary_unclosed_question"] == 50

    def test_boundary_unclosed_not_emitted_when_options_complete(self):
        """末题已含 D 选项 → 不警告。"""
        pipeline = ImportPipeline()
        fake_questions = [
            {"number": 50, "page_start": 39, "page_end": 40, "raw_question_text": "Q50",
             "has_options": True, "option_lines": {"A": "a", "B": "b", "C": "c", "D": "d"}},
        ]
        seen_hashes: set = set()
        with patch(
            "app.features.pipeline_orchestrator.split_questions",
            return_value=fake_questions,
        ):
            result = pipeline._run_split(
                normalized_blocks=[{"page": 40, "block_index": 0, "normalized_text": "x", "raw_text": "x"}],
                _chunk_seen_hashes=seen_hashes,
                _chunk_logical_end=40,
            )
        assert not any("chunk_boundary_unclosed" in w for w in result["warnings"])

    def test_boundary_unclosed_not_emitted_for_two_option_question(self):
        """P1-2: 双选题（只有 A/B）不应误报 chunk_boundary_unclosed。"""
        pipeline = ImportPipeline()
        fake_questions = [
            {"number": 50, "page_start": 39, "page_end": 40, "raw_question_text": "对错判断",
             "has_options": True, "option_lines": {"A": "正确", "B": "错误"}},
        ]
        seen_hashes: set = set()
        with patch(
            "app.features.pipeline_orchestrator.split_questions",
            return_value=fake_questions,
        ):
            result = pipeline._run_split(
                normalized_blocks=[{"page": 40, "block_index": 0, "normalized_text": "x", "raw_text": "x"}],
                _chunk_seen_hashes=seen_hashes,
                _chunk_logical_end=40,
            )
        assert not any("chunk_boundary_unclosed" in w for w in result["warnings"])
        assert "boundary_unclosed_question" not in result["split_diagnostics"]

    def test_boundary_unclosed_not_emitted_for_short_answer(self):
        """P1-2: 简答题 has_options=False 不应误报。"""
        pipeline = ImportPipeline()
        fake_questions = [
            {"number": 50, "page_start": 39, "page_end": 40, "raw_question_text": "简述...",
             "has_options": False, "option_lines": {}},
        ]
        seen_hashes: set = set()
        with patch(
            "app.features.pipeline_orchestrator.split_questions",
            return_value=fake_questions,
        ):
            result = pipeline._run_split(
                normalized_blocks=[{"page": 40, "block_index": 0, "normalized_text": "x", "raw_text": "x"}],
                _chunk_seen_hashes=seen_hashes,
                _chunk_logical_end=40,
            )
        assert not any("chunk_boundary_unclosed" in w for w in result["warnings"])

    def test_boundary_unclosed_not_emitted_when_far_from_boundary(self):
        """P1-2: 末题 page_end 远离 logical_end（>1 页）不报警。"""
        pipeline = ImportPipeline()
        fake_questions = [
            # page_end=35 vs logical_end=40 差 5 页，不算贴合边界
            {"number": 30, "page_start": 34, "page_end": 35, "raw_question_text": "Q30",
             "has_options": True, "option_lines": {"A": "a", "B": "b", "C": "c"}},
        ]
        seen_hashes: set = set()
        with patch(
            "app.features.pipeline_orchestrator.split_questions",
            return_value=fake_questions,
        ):
            result = pipeline._run_split(
                normalized_blocks=[{"page": 35, "block_index": 0, "normalized_text": "x", "raw_text": "x"}],
                _chunk_seen_hashes=seen_hashes,
                _chunk_logical_end=40,
            )
        assert not any("chunk_boundary_unclosed" in w for w in result["warnings"])

    def test_boundary_unclosed_not_emitted_when_only_a_b(self):
        """P1-2: 仅 A/B（缺 C）也不算 truncated 4-option，不报警。"""
        pipeline = ImportPipeline()
        fake_questions = [
            {"number": 50, "page_start": 39, "page_end": 40, "raw_question_text": "Q50",
             "has_options": True, "option_lines": {"A": "a", "B": "b"}},
        ]
        seen_hashes: set = set()
        with patch(
            "app.features.pipeline_orchestrator.split_questions",
            return_value=fake_questions,
        ):
            result = pipeline._run_split(
                normalized_blocks=[{"page": 40, "block_index": 0, "normalized_text": "x", "raw_text": "x"}],
                _chunk_seen_hashes=seen_hashes,
                _chunk_logical_end=40,
            )
        assert not any("chunk_boundary_unclosed" in w for w in result["warnings"])

    def test_legacy_single_pass_skips_overlap_logic(self):
        """没有 _chunk_seen_hashes / _chunk_logical_end → P2-3 逻辑不介入。"""
        pipeline = ImportPipeline()
        fake_questions = [
            {"number": 1, "page_start": 1, "page_end": 1, "raw_question_text": "Q1",
             "has_options": True, "option_lines": {"A": "a", "B": "b", "C": "c"}},
        ]
        with patch(
            "app.features.pipeline_orchestrator.split_questions",
            return_value=fake_questions,
        ):
            result = pipeline._run_split(
                normalized_blocks=[{"page": 1, "block_index": 0, "normalized_text": "x", "raw_text": "x"}],
            )
        # 不出现任何 P2-3 警告字串
        assert not any("boundary_overlap_skipped" in w for w in result["warnings"])
        assert not any("chunk_boundary_unclosed" in w for w in result["warnings"])
        assert "overlap_skipped_numbers" not in result["split_diagnostics"]
        assert "boundary_unclosed_question" not in result["split_diagnostics"]


class TestChunkedRunWithOverlap:
    """端到端验证 _run_chunked 把 overlap 正确传给 _run_single_pass。"""

    def test_effective_page_end_extended_by_overlap(self, tmp_path):
        """非末 chunk 的 page_end 被 +overlap 扩展；末 chunk 不扩展。"""
        async def _go():
            sm, _ = await _make_session(tmp_path)
            async with sm() as db:
                pipeline = ImportPipeline()
                pipeline.pipeline_id = "pl_overlap_001"
                _stub_pipeline_stages(pipeline, written_per_chunk=0)

                effective_ends: list[tuple] = []

                def _capture(*, file_content=None, source_type="pdf", file_path=None, **kw):
                    opts = kw.get("options") or {}
                    effective_ends.append((opts.get("page_start"), opts.get("page_end")))
                    return {"raw_blocks": [], "extracted": 0}

                pipeline._run_extract = MagicMock(side_effect=_capture)

                with patch.dict(os.environ, {
                    "IMPORT_PIPELINE_CHUNK_SIZE": "40",
                    "IMPORT_PIPELINE_CHUNK_OVERLAP": "3",
                }):
                    with patch(
                        "app.features.pipeline_orchestrator._read_pdf_page_count",
                        return_value=120,
                    ):
                        with _mock_render_pages(120):
                            result = await pipeline.run(
                            file_path="/tmp/fake.pdf",
                            source_type="pdf",
                            source_file="x.pdf",
                            db=db,
                        )

                # 3 chunks: (1,40)+3=43, (41,80)+3=83, (81,120) 末 chunk 不扩
                assert effective_ends == [(1, 43), (41, 83), (81, 120)]
                # diagnostics 记录 chunk_overlap
                assert result["diagnostics"]["chunk_overlap"] == 3
                chunks = result["diagnostics"]["chunks"]
                # logical page_end 不变；effective 在 diagnostics 里多记一份
                assert chunks[0]["page_end"] == 40
                assert chunks[0]["effective_page_end"] == 43
                assert chunks[1]["page_end"] == 80
                assert chunks[1]["effective_page_end"] == 83
                assert chunks[2]["page_end"] == 120
                assert chunks[2]["effective_page_end"] == 120

        _run(_go())

    def test_zero_overlap_disables_extension(self, tmp_path):
        """IMPORT_PIPELINE_CHUNK_OVERLAP=0 → effective_page_end == logical end。"""
        async def _go():
            sm, _ = await _make_session(tmp_path)
            async with sm() as db:
                pipeline = ImportPipeline()
                pipeline.pipeline_id = "pl_overlap_zero_001"
                _stub_pipeline_stages(pipeline, written_per_chunk=0)

                effective_ends: list[tuple] = []

                def _capture(*, file_content=None, source_type="pdf", file_path=None, **kw):
                    opts = kw.get("options") or {}
                    effective_ends.append((opts.get("page_start"), opts.get("page_end")))
                    return {"raw_blocks": [], "extracted": 0}

                pipeline._run_extract = MagicMock(side_effect=_capture)

                with patch.dict(os.environ, {
                    "IMPORT_PIPELINE_CHUNK_SIZE": "40",
                    "IMPORT_PIPELINE_CHUNK_OVERLAP": "0",
                }):
                    with patch(
                        "app.features.pipeline_orchestrator._read_pdf_page_count",
                        return_value=80,
                    ):
                        with _mock_render_pages(80):
                            result = await pipeline.run(
                            file_path="/tmp/fake.pdf",
                            source_type="pdf",
                            source_file="x.pdf",
                            db=db,
                        )

                assert effective_ends == [(1, 40), (41, 80)]
                assert result["diagnostics"]["chunk_overlap"] == 0

        _run(_go())


# ---------------------------------------------------------------------------
# P0-3 per-chunk session
# ---------------------------------------------------------------------------


class TestChunkedUsesPerChunkSession:
    """P0-3: chunked 路径每个 chunk 用独立 AsyncSession，避免长事务。"""

    def test_chunked_uses_per_chunk_session(self, tmp_path):
        """跑 3 chunks 的 chunked pipeline，断言 session_factory 被
        ``__aenter__`` 至少 3 次（每 chunk 至少一次）。"""

        async def _go():
            sm, _ = await _make_session(tmp_path)

            enter_count = {"n": 0}
            real_factory = sm

            class _CountingFactory:
                def __call__(self, *args, **kwargs):
                    enter_count["n"] += 1
                    return real_factory(*args, **kwargs)

            counting_factory = _CountingFactory()

            async with sm() as db:
                pipeline = ImportPipeline()
                pipeline.pipeline_id = "pl_per_chunk_session_001"
                _stub_pipeline_stages(pipeline, written_per_chunk=2)

                with patch(
                    "app.features.pipeline_orchestrator._derive_session_factory",
                    return_value=counting_factory,
                ):
                    with patch.dict(os.environ, {"IMPORT_PIPELINE_CHUNK_SIZE": "40"}):
                        with patch(
                            "app.features.pipeline_orchestrator._read_pdf_page_count",
                            return_value=120,
                        ):
                            with _mock_render_pages(120):
                                result = await pipeline.run(
                                file_path="/tmp/fake.pdf",
                                source_type="pdf",
                                source_file="x.pdf",
                                db=db,
                            )

                assert result["status"] == "completed"
                assert result["stats"]["total_chunks"] == 3
                # 至少 3 次 chunk 用 + 初始化 + 收尾 → 5+。下限定 3 即可
                # 满足"每 chunk 至少一次"的契约。
                assert enter_count["n"] >= 3, (
                    f"expected ≥3 session enters (one per chunk), got {enter_count['n']}"
                )

        _run(_go())


# ---------------------------------------------------------------------------
# P1-1 GlobalHashIndex finally release
# ---------------------------------------------------------------------------


class TestChunkedReleasesHashIndex:
    """P1-1: chunk loop 完成或异常都要清空 hash_index 的内部 dict，
    避免大字典残留在 GlobalHashIndex 实例上（低配 2C2G 服务器友好）。"""

    def test_hash_index_cleared_on_happy_path(self, tmp_path):
        """正常完成的 chunked 跑批，跑完后 hash_index 内部 dict 为空。"""

        async def _go():
            sm, _ = await _make_session(tmp_path)

            captured = {"index": None}
            real_factory_cls = None

            async with sm() as db:
                from app.features import global_hash_index as ghi_mod
                real_factory_cls = ghi_mod.GlobalHashIndex

                class _CapturingIndex(real_factory_cls):
                    def __init__(self):
                        super().__init__()
                        captured["index"] = self
                        # 预填两条假数据，断言 finally 真的清空了它
                        self._question_index[("math", "h1")] = 1
                        self._import_index[("math", "h2")] = 2

                pipeline = ImportPipeline()
                pipeline.pipeline_id = "pl_hashidx_clear_001"
                _stub_pipeline_stages(pipeline, written_per_chunk=2)

                with patch(
                    "app.features.pipeline_orchestrator._derive_session_factory",
                    return_value=sm,
                ):
                    with patch(
                        "app.features.global_hash_index.GlobalHashIndex",
                        _CapturingIndex,
                    ):
                        with patch.dict(os.environ, {"IMPORT_PIPELINE_CHUNK_SIZE": "40"}):
                            with patch(
                                "app.features.pipeline_orchestrator._read_pdf_page_count",
                                return_value=80,
                            ):
                                with _mock_render_pages(80):
                                    result = await pipeline.run(
                                    file_path="/tmp/fake.pdf",
                                    source_type="pdf",
                                    source_file="x.pdf",
                                    db=db,
                                )

                assert result["status"] == "completed"
                idx = captured["index"]
                assert idx is not None, "GlobalHashIndex was never constructed"
                assert idx._question_index == {}, "question_index should be cleared in finally"
                assert idx._import_index == {}, "import_index should be cleared in finally"

        _run(_go())

    def test_hash_index_cleared_when_chunk_raises(self, tmp_path):
        """chunk 跑批中抛异常时，finally 仍要清空 hash_index 内部 dict。"""

        async def _go():
            sm, _ = await _make_session(tmp_path)

            captured = {"index": None}

            async with sm() as db:
                from app.features import global_hash_index as ghi_mod
                real_factory_cls = ghi_mod.GlobalHashIndex

                class _CapturingIndex(real_factory_cls):
                    def __init__(self):
                        super().__init__()
                        captured["index"] = self
                        self._question_index[("math", "h1")] = 1
                        self._import_index[("math", "h2")] = 2

                pipeline = ImportPipeline()
                pipeline.pipeline_id = "pl_hashidx_clear_002"
                _stub_pipeline_stages(pipeline, written_per_chunk=2)

                # 让 _execute_chunk 直接抛异常（绕过其内部 try/except，
                # 模拟 chunk 边界外的失败路径，比如 session_factory 返回的
                # context manager __aexit__ 出错）。
                async def _boom(*args, **kwargs):
                    raise RuntimeError("simulated chunk crash")

                with patch.object(pipeline, "_execute_chunk", side_effect=_boom):
                    with patch(
                        "app.features.pipeline_orchestrator._derive_session_factory",
                        return_value=sm,
                    ):
                        with patch(
                            "app.features.global_hash_index.GlobalHashIndex",
                            _CapturingIndex,
                        ):
                            with patch.dict(os.environ, {"IMPORT_PIPELINE_CHUNK_SIZE": "40"}):
                                with patch(
                                    "app.features.pipeline_orchestrator._read_pdf_page_count",
                                    return_value=80,
                                ):
                                    with _mock_render_pages(80):
                                        with pytest.raises(RuntimeError, match="simulated chunk crash"):
                                            await pipeline.run(
                                                file_path="/tmp/fake.pdf",
                                                source_type="pdf",
                                                source_file="x.pdf",
                                                db=db,
                                            )

                idx = captured["index"]
                assert idx is not None, "GlobalHashIndex was never constructed"
                assert idx._question_index == {}, (
                    "question_index should be cleared even when chunk raises"
                )
                assert idx._import_index == {}, (
                    "import_index should be cleared even when chunk raises"
                )

        _run(_go())
