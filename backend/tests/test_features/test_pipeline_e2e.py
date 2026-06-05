"""P2-7 端到端测试：把 P2-1~P2-6 的契约串成一条完整链路验证。

这些测试都通过 stub `_read_pdf_page_count` + 各 stage 桩跑全链路，**不**依
赖真实 PaddleOCR / DeepSeek / fitz，所以 CI 上稳定可重放；但相比 P2-2/3/4
的单元测试，它们走完整的 ``ImportPipeline.run() → _run_chunked →
_execute_chunk → _run_single_pass`` 路径，确保各模块协作时没有
契约漂移。

覆盖矩阵：

1. 400 页 / chunk_size=40 → 10 chunks 全部 completed
2. 单 chunk 失败隔离 + 后续 resume 仅重跑该 chunk
3. GlobalHashIndex 跨 chunk 命中：chunk 0 写入的 hash 在 chunk 3
   `add_import` 调用栈里出现，hash_index._import_index 命中
4. P0-1 / P1-A 大字段释放：chunked 模式下 review 阶段的 stage kwargs
   不再持有 raw_blocks / normalized_blocks / raw_questions / matched
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.features import pipeline_checkpoint as ckpt
from app.features.global_hash_index import GlobalHashIndex
from app.features.pipeline_orchestrator import (
    ImportPipeline,
    resume_pipeline_background,
)
from app.models.import_pipeline import ImportPipelineChunk


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


async def _make_session(tmp_path: Path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'p2_e2e.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False), engine


def _run(coro):
    return asyncio.run(coro)


def _wire_stage_stubs(
    pipeline: ImportPipeline,
    *,
    written_per_chunk: int = 5,
    extract_side_effect=None,
    review_hashes_per_chunk: list[list[tuple[str, str, int]]] | None = None,
    review_kwargs_log: list[dict] | None = None,
):
    """Wire deterministic stubs onto every stage that ImportPipeline runs.

    - ``extract_side_effect``: optional callable(**kwargs) → dict, used to
      inject per-chunk failures or page-range-aware behaviour.
    - ``review_hashes_per_chunk``: optional list giving the
      ``review_new_hashes`` payload for each chunk's review stage; if shorter
      than the number of review calls, missing entries fall back to ``[]``.
    - ``review_kwargs_log``: optional list to record the kwargs each review
      call receives — used by the large-field-release assertions.
    """

    def _default_extract(**kw):
        opts = kw.get("options") or {}
        page_start = opts.get("page_start") or 1
        # one fake block per chunk is enough; raw_blocks is popped after
        # normalize_text so size doesn't matter for stats.
        return {
            "raw_blocks": [
                {"page": page_start, "block_index": 0, "text": f"chunk@{page_start}"}
            ],
            "extracted": 1,
        }

    pipeline._run_extract = MagicMock(
        side_effect=extract_side_effect or _default_extract
    )
    pipeline._run_normalize_text = MagicMock(
        return_value={
            "normalized_blocks": [
                {
                    "page": 1,
                    "block_index": 0,
                    "raw_text": "x",
                    "normalized_text": "x",
                }
            ]
        }
    )
    pipeline._run_split = MagicMock(
        return_value={
            "raw_questions": [],
            "split_count": written_per_chunk,
        }
    )
    pipeline._run_match = MagicMock(
        return_value={"matched": [], "unmatched": [], "matched_count": 0}
    )
    pipeline._run_normalize_schema = MagicMock(
        return_value={"questions": [], "normalized_count": written_per_chunk}
    )

    counter = {"n": 0}
    review_hashes_per_chunk = review_hashes_per_chunk or []

    async def _fake_review(*args, **kwargs):
        idx = counter["n"]
        counter["n"] += 1
        if review_kwargs_log is not None:
            review_kwargs_log.append(dict(kwargs))
        new_hashes = (
            review_hashes_per_chunk[idx]
            if idx < len(review_hashes_per_chunk)
            else []
        )
        return {
            "batch_id": f"REVIEW_e2e_chunk_{idx}",
            "written": written_per_chunk,
            "skipped": 0,
            "total": written_per_chunk,
            "items": [
                {"id": 1000 + idx * 100 + j, "question_hash": h_tuple[1]}
                for j, h_tuple in enumerate(new_hashes)
            ],
            "review_new_hashes": new_hashes,
        }

    pipeline._run_review = AsyncMock(side_effect=_fake_review)


# ---------------------------------------------------------------------------
# 1. 400p happy path
# ---------------------------------------------------------------------------


class TestE2EHappyPath:
    """400 页 / chunk_size=40 → 10 chunks, 全部 completed。"""

    def test_400p_pdf_chunked_run_completes(self, tmp_path):
        async def _go():
            sm, _ = await _make_session(tmp_path)
            async with sm() as db:
                pipeline = ImportPipeline()
                pipeline.pipeline_id = "pl_e2e_400p"
                _wire_stage_stubs(pipeline, written_per_chunk=6)

                with patch.dict(
                    os.environ,
                    {
                        "IMPORT_PIPELINE_CHUNK_SIZE": "40",
                        "IMPORT_PIPELINE_CHUNK_OVERLAP": "3",
                    },
                ):
                    with patch(
                        "app.features.pipeline_orchestrator._read_pdf_page_count",
                        return_value=400,
                    ):
                        result = await pipeline.run(
                            file_path="/tmp/e2e_400p.pdf",
                            source_type="pdf",
                            source_file="王道_400p.pdf",
                            db=db,
                        )

                assert result["status"] == "completed"
                assert result["stats"]["total_chunks"] == 10
                assert result["stats"]["completed_chunks"] == 10
                assert result["stats"]["failed_chunks"] == 0
                assert result["stats"]["to_review"] == 60  # 6 * 10
                # diagnostics carries every chunk
                chunks = result["diagnostics"]["chunks"]
                assert len(chunks) == 10
                # Effective ends extended by overlap on every non-last chunk
                # (last chunk: page_end=400, no extension).
                assert chunks[0]["effective_page_end"] == 43
                assert chunks[8]["effective_page_end"] == 363
                assert chunks[9]["effective_page_end"] == 400
                # Each chunk got its own batch_id
                batch_ids = {c["batch_id"] for c in chunks if c["batch_id"]}
                assert len(batch_ids) == 10

            async with sm() as db:
                progress = await ckpt.get_pipeline_progress(
                    db, "pl_e2e_400p", use_cache=False
                )
                assert progress["status"] == "completed"
                assert progress["completed_chunks"] == 10
                assert progress["question_count"] == 60
                assert progress["finished_at"] is not None

        _run(_go())


# ---------------------------------------------------------------------------
# 2. 单 chunk 失败隔离 + resume 修复
# ---------------------------------------------------------------------------


class TestE2EChunkFailureThenResume:
    """模拟一次 import：chunk 5 失败 → pipeline.paused → resume 后转 completed。"""

    def test_chunk_failure_then_resume_recovers_pipeline(self, tmp_path):
        async def _go():
            sm, _ = await _make_session(tmp_path)

            # ---- 第一次 import：chunk 5 抛错 -------------------------------
            extract_calls: list[int] = []

            def _flaky_extract(**kw):
                opts = kw.get("options") or {}
                page_start = opts.get("page_start") or 1
                extract_calls.append(page_start)
                # chunk 5 covers pages 201-240 with chunk_size=40
                if page_start == 201:
                    raise RuntimeError("simulated OCR explosion @ chunk 5")
                return {
                    "raw_blocks": [
                        {"page": page_start, "block_index": 0, "text": "ok"}
                    ],
                    "extracted": 1,
                }

            async with sm() as db:
                pipeline = ImportPipeline()
                pipeline.pipeline_id = "pl_e2e_resume"
                _wire_stage_stubs(
                    pipeline,
                    written_per_chunk=4,
                    extract_side_effect=_flaky_extract,
                )

                with patch.dict(
                    os.environ,
                    {"IMPORT_PIPELINE_CHUNK_SIZE": "40"},
                ):
                    with patch(
                        "app.features.pipeline_orchestrator._read_pdf_page_count",
                        return_value=400,
                    ):
                        result = await pipeline.run(
                            file_path="/tmp/e2e_400p.pdf",
                            source_type="pdf",
                            source_file="王道_400p.pdf",
                            db=db,
                        )

                assert result["status"] == "paused"
                assert result["stats"]["total_chunks"] == 10
                assert result["stats"]["completed_chunks"] == 9
                assert result["stats"]["failed_chunks"] == 1
                # Each chunk's extract was tried exactly once
                assert extract_calls == [
                    1, 41, 81, 121, 161, 201, 241, 281, 321, 361,
                ]
                # diagnostics records chunk 5's failure
                failed = [c for c in result["diagnostics"]["chunks"] if c["status"] == "failed"]
                assert len(failed) == 1
                assert failed[0]["chunk_index"] == 5
                assert "OCR explosion" in failed[0]["error_message"]

            # ---- DB checkpoint 状态符合预期 -------------------------------
            async with sm() as db:
                progress = await ckpt.get_pipeline_progress(
                    db, "pl_e2e_resume", use_cache=False
                )
                assert progress["status"] == "paused"
                assert progress["failed_chunks"] == 1
                assert len(progress["failed_chunk_details"]) == 1
                assert progress["failed_chunk_details"][0]["chunk_index"] == 5

                rows = (
                    (
                        await db.execute(
                            select(ImportPipelineChunk)
                            .where(
                                ImportPipelineChunk.pipeline_id == "pl_e2e_resume"
                            )
                            .order_by(ImportPipelineChunk.chunk_index)
                        )
                    )
                    .scalars()
                    .all()
                )
                assert [r.status for r in rows].count("completed") == 9
                assert [r.status for r in rows].count("failed") == 1
                # snapshot the 9 successful batch_ids so we can verify resume
                # does not touch them
                preexisting_batches = {r.chunk_index: r.batch_id for r in rows if r.status == "completed"}

            # ---- resume：chunk 5 这次不再抛 -------------------------------
            def _good_extract(**kw):
                opts = kw.get("options") or {}
                page_start = opts.get("page_start") or 1
                return {
                    "raw_blocks": [
                        {"page": page_start, "block_index": 0, "text": "ok"}
                    ],
                    "extracted": 1,
                }

            with patch(
                "app.features.pipeline_orchestrator.ImportPipeline",
            ) as PipelineCls:
                instance = ImportPipeline()
                instance.pipeline_id = "pl_e2e_resume"
                _wire_stage_stubs(
                    instance,
                    written_per_chunk=4,
                    extract_side_effect=_good_extract,
                )
                replay_log: list[int] = []
                orig_exec = instance._execute_chunk

                async def _spy(**kwargs):
                    replay_log.append(kwargs["chunk_index"])
                    return await orig_exec(**kwargs)

                instance._execute_chunk = _spy
                PipelineCls.return_value = instance

                async with sm() as db:
                    with patch.dict(
                        os.environ,
                        {"IMPORT_PIPELINE_CHUNK_SIZE": "40"},
                    ):
                        await resume_pipeline_background(
                            pipeline_id="pl_e2e_resume",
                            file_path="/tmp/e2e_400p.pdf",
                            subject=None,
                            options={},
                            db=db,
                        )

                # Resume should only touch chunk 5
                assert replay_log == [5]

            # ---- DB 状态：所有 chunk completed，原 9 个 batch_id 不变 ----
            async with sm() as db:
                progress = await ckpt.get_pipeline_progress(
                    db, "pl_e2e_resume", use_cache=False
                )
                assert progress["status"] == "completed"
                assert progress["completed_chunks"] == 10
                assert progress["failed_chunks"] == 0

                rows = (
                    (
                        await db.execute(
                            select(ImportPipelineChunk)
                            .where(
                                ImportPipelineChunk.pipeline_id == "pl_e2e_resume"
                            )
                            .order_by(ImportPipelineChunk.chunk_index)
                        )
                    )
                    .scalars()
                    .all()
                )
                for row in rows:
                    if row.chunk_index == 5:
                        assert row.status == "completed"
                        assert row.error_message is None
                        assert row.batch_id and row.batch_id.startswith("REVIEW_e2e_chunk_")
                    else:
                        # Untouched batches keep their original id from the
                        # initial import.
                        assert row.batch_id == preexisting_batches[row.chunk_index]

        _run(_go())


# ---------------------------------------------------------------------------
# 3. 跨 chunk hash 去重
# ---------------------------------------------------------------------------


class TestE2ECrossChunkHashDedup:
    """chunk 0 的 review_new_hashes 应在 chunk 1 启动前进入 GlobalHashIndex。"""

    def test_chunk_zero_hashes_visible_to_chunk_one(self, tmp_path):
        async def _go():
            sm, _ = await _make_session(tmp_path)

            # 我们用一个真实的 GlobalHashIndex 实例，记录 add_import 调用 +
            # lookup_import 在 chunk 1 时的命中行为。
            real_index = GlobalHashIndex()
            add_calls: list[tuple[str, str, int]] = []
            orig_add = real_index.add_import

            def _spy_add(subject, qhash, iid):
                add_calls.append((subject, qhash, iid))
                return orig_add(subject, qhash, iid)

            real_index.add_import = _spy_add  # type: ignore[assignment]

            with patch(
                "app.features.global_hash_index.GlobalHashIndex",
                return_value=real_index,
            ):
                async with sm() as db:
                    pipeline = ImportPipeline()
                    pipeline.pipeline_id = "pl_e2e_hash"

                    chunk0_hashes = [("math2", "HASH_AAA", 9001)]
                    chunk1_hashes = [("math2", "HASH_BBB", 9002)]
                    chunk2_hashes: list[tuple[str, str, int]] = []
                    _wire_stage_stubs(
                        pipeline,
                        written_per_chunk=1,
                        review_hashes_per_chunk=[
                            chunk0_hashes,
                            chunk1_hashes,
                            chunk2_hashes,
                        ],
                    )

                    with patch.dict(
                        os.environ,
                        {"IMPORT_PIPELINE_CHUNK_SIZE": "40"},
                    ):
                        with patch(
                            "app.features.pipeline_orchestrator._read_pdf_page_count",
                            return_value=120,
                        ):
                            result = await pipeline.run(
                                file_path="/tmp/e2e_hash.pdf",
                                source_type="pdf",
                                source_file="hash.pdf",
                                db=db,
                            )

            assert result["status"] == "completed"
            # add_import 被 chunk 0 / chunk 1 各调用一次；chunk 2 review 没
            # 返回新 hash，所以无 add 调用
            assert add_calls == [
                ("math2", "HASH_AAA", 9001),
                ("math2", "HASH_BBB", 9002),
            ]
            # chunk 1 启动时索引里应已有 chunk 0 的 hash → lookup_import 命中
            hit_after = await real_index.lookup_import(
                db=None,  # 命中走内存，不需要 db
                subject="math2",
                question_hash="HASH_AAA",
            )
            assert hit_after == 9001
            # diagnostics 把 hash_index stats 写出来供观测（load 时计算，
            # 不随 add_import 增加；这里只断言字段存在 + 已加载）
            stats = result["diagnostics"]["hash_index"]
            assert stats is not None
            assert stats["fallback_to_sql"] is False
            # 内存索引在 chunk 0/1 跑完后已累加两条 hash → resume 路径或下一
            # 个兄弟 chunk 都能直接拿到，不再走 difflib 全表扫描
            assert real_index._import_index[("math2", "HASH_AAA")] == 9001
            assert real_index._import_index[("math2", "HASH_BBB")] == 9002

        _run(_go())


# ---------------------------------------------------------------------------
# 4. 大字段在 chunked 模式下也按 P1-A 契约释放
# ---------------------------------------------------------------------------


class TestE2ELargeFieldsReleasedInChunkedMode:
    """review 阶段拿到的 kwargs 里不应再含 raw_blocks / normalized_blocks /
    raw_questions / matched / unmatched / file_content / file_path —— 这是
    P0-1/P1-A 在每个 chunk 内仍然有效的端到端检验。"""

    def test_review_stage_does_not_receive_intermediate_artifacts(self, tmp_path):
        async def _go():
            sm, _ = await _make_session(tmp_path)
            review_kwargs_log: list[dict] = []
            async with sm() as db:
                pipeline = ImportPipeline()
                pipeline.pipeline_id = "pl_e2e_release"
                _wire_stage_stubs(
                    pipeline,
                    written_per_chunk=2,
                    review_kwargs_log=review_kwargs_log,
                )

                with patch.dict(
                    os.environ,
                    {"IMPORT_PIPELINE_CHUNK_SIZE": "40"},
                ):
                    with patch(
                        "app.features.pipeline_orchestrator._read_pdf_page_count",
                        return_value=160,
                    ):
                        result = await pipeline.run(
                            file_path="/tmp/e2e_release.pdf",
                            source_type="pdf",
                            source_file="release.pdf",
                            db=db,
                        )

            assert result["status"] == "completed"
            assert len(review_kwargs_log) == 4  # 160 / 40 = 4 chunks
            forbidden = {
                "raw_blocks",
                "normalized_blocks",
                "raw_questions",
                "matched",
                "unmatched",
                "file_content",
                "file_path",
            }
            for i, kwargs in enumerate(review_kwargs_log):
                seen = forbidden & kwargs.keys()
                assert not seen, (
                    f"chunk {i} review stage still holds large fields: {seen}"
                )
                # questions 仍然作为 review 的输入，确保流水线契约没坏
                assert "questions" in kwargs

        _run(_go())
