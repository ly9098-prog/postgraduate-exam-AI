"""Stage 8 流水线编排 — 单元测试。"""
import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.features.pipeline_orchestrator import (
    ImportPipeline,
    PipelineStage,
    _extract_pdf_blocks,
    _extract_text_blocks,
    _ocr_scanned_pdf,
    _pipeline_store,
    get_pipeline_status,
    run_import_pipeline,
    run_pipeline_background,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_raw_blocks(n=2):
    return [{"page": i + 1, "block_index": i, "text": f"Block {i + 1} text."} for i in range(n)]


def _make_normalized_blocks(n=2):
    return [
        {"page": i + 1, "block_index": i, "raw_text": f"Block {i + 1} text.", "normalized_text": f"Block {i + 1} text."}
        for i in range(n)
    ]


def _make_raw_questions(n=2):
    return [
        {
            "number": i + 1,
            "raw_question_text": f"Question {i + 1} text",
            "page_start": 1,
            "page_end": 1,
            "has_options": True,
            "option_lines": {"A": "x", "B": "y", "C": "z", "D": "w"},
            "confidence": 0.9,
        }
        for i in range(n)
    ]


def _make_matched(n=2):
    return [
        {
            "question_number": i + 1,
            "answer": "A",
            "explanation": f"Explanation {i + 1}",
            "answer_source": "inline",
            "explanation_source": "inline",
            "confidence": 0.9,
        }
        for i in range(n)
    ]


def _make_questions(n=2):
    return [
        {
            "schema_version": "v1",
            "subject": "math2",
            "question_type": "single_choice",
            "stem": f"Question {i + 1} stem",
            "options": [{"key": k, "text": v} for k, v in [("A", "x"), ("B", "y"), ("C", "z"), ("D", "w")]],
            "answer": "A",
            "analysis": f"Explanation {i + 1}",
            "raw_text": f"Question {i + 1} text",
            "knowledge_points": [],
            "difficulty": 3,
            "source": {"file": "test.pdf", "type": "pdf", "page": 1},
            "is_valid": True,
            "errors": [],
            "warnings": [],
            "stem_hash": f"abc{i}",
            "confidence_score": 0.85,
        }
        for i in range(n)
    ]


def _make_mock_db():
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.execute = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# _extract_text_blocks
# ---------------------------------------------------------------------------


class TestExtractTextBlocks:
    def test_extracts_text(self):
        blocks = _extract_text_blocks(b"Hello\nWorld")
        assert len(blocks) == 1
        assert blocks[0]["page"] == 1
        assert blocks[0]["text"] == "Hello\nWorld"

    def test_empty_content(self):
        with pytest.raises(ValueError, match="文本内容为空"):
            _extract_text_blocks(b"   ")

    def test_utf8_decoding(self):
        blocks = _extract_text_blocks("高等数学\n线性代数".encode("utf-8"))
        assert len(blocks) == 1
        assert "高等数学" in blocks[0]["text"]


# ---------------------------------------------------------------------------
# _extract_pdf_blocks
# ---------------------------------------------------------------------------


class TestExtractPdfBlocks:
    def test_extracts_pages(self):
        mock_fitz = MagicMock()
        mock_doc = MagicMock()
        mock_page = MagicMock()
        mock_page.get_text.return_value = "Page content"
        mock_doc.__len__ = MagicMock(return_value=1)
        mock_doc.__getitem__ = MagicMock(return_value=mock_page)
        mock_fitz.open.return_value = mock_doc

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            blocks = _extract_pdf_blocks(b"fake pdf content")

        assert len(blocks) == 1
        assert blocks[0]["page"] == 1
        assert blocks[0]["text"] == "Page content"
        mock_doc.close.assert_called_once()

    def test_skips_empty_pages(self):
        mock_fitz = MagicMock()
        mock_doc = MagicMock()
        page1 = MagicMock()
        page1.get_text.return_value = ""
        page2 = MagicMock()
        page2.get_text.return_value = "Content"
        mock_doc.__len__ = MagicMock(return_value=2)
        mock_doc.__getitem__ = MagicMock(side_effect=[page1, page2])
        mock_fitz.open.return_value = mock_doc

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            blocks = _extract_pdf_blocks(b"fake pdf")

        assert len(blocks) == 1
        assert blocks[0]["page"] == 2

    def test_all_empty_returns_empty_list(self):
        mock_fitz = MagicMock()
        mock_doc = MagicMock()
        mock_page = MagicMock()
        mock_page.get_text.return_value = "   "
        mock_doc.__len__ = MagicMock(return_value=1)
        mock_doc.__getitem__ = MagicMock(return_value=mock_page)
        mock_fitz.open.return_value = mock_doc

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            result = _extract_pdf_blocks(b"empty pdf")
            assert result == []

    def test_no_fitz_raises(self):
        with patch.dict(sys.modules, {"fitz": None}):
            with pytest.raises(RuntimeError, match="PyMuPDF"):
                _extract_pdf_blocks(b"any content")


# ---------------------------------------------------------------------------
# _ocr_scanned_pdf
# ---------------------------------------------------------------------------


class TestOcrScannedPdf:
    def test_renders_pages_and_calls_ocr(self):
        from app.services.ocr_service import OcrPageResult

        mock_fitz = MagicMock()
        mock_doc = MagicMock()
        mock_page = MagicMock()
        mock_pix = MagicMock()
        mock_pix.tobytes.return_value = b"fake_png"
        mock_pix.width = 800
        mock_pix.height = 600
        mock_page.get_pixmap.return_value = mock_pix
        mock_doc.__len__ = MagicMock(return_value=1)
        mock_doc.__getitem__ = MagicMock(return_value=mock_page)
        mock_fitz.open.return_value = mock_doc

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            with patch(
                "app.services.ocr_service.ocr_pages_with_boxes",
                return_value={1: OcrPageResult(page_index=1, text="OCR识别结果", boxes=[])},
            ) as mock_ocr:
                with patch(
                    "app.services.ocr_service.clean_ocr_text",
                    side_effect=lambda t: t,
                ):
                    blocks = _ocr_scanned_pdf(b"pdf bytes")

        assert len(blocks) == 1
        assert blocks[0]["page"] == 1
        assert blocks[0]["text"] == "OCR识别结果"
        mock_ocr.assert_called_once_with([(1, b"fake_png")], skip_rotation=True)
        mock_doc.close.assert_called_once()

    def test_skips_empty_ocr_pages(self):
        from app.services.ocr_service import OcrPageResult

        mock_fitz = MagicMock()
        mock_doc = MagicMock()
        pages = []
        for _ in range(2):
            p = MagicMock()
            pix = MagicMock()
            pix.tobytes.return_value = b"png"
            pix.width = 800
            pix.height = 600
            p.get_pixmap.return_value = pix
            pages.append(p)
        mock_doc.__len__ = MagicMock(return_value=2)
        mock_doc.__getitem__ = MagicMock(side_effect=lambda i: pages[i])
        mock_fitz.open.return_value = mock_doc

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            with patch(
                "app.services.ocr_service.ocr_pages_with_boxes",
                return_value={
                    1: OcrPageResult(page_index=1, text="", boxes=[]),
                    2: OcrPageResult(page_index=2, text="第二页内容", boxes=[]),
                },
            ):
                with patch(
                    "app.services.ocr_service.clean_ocr_text",
                    side_effect=lambda t: t,
                ):
                    blocks = _ocr_scanned_pdf(b"pdf")

        assert len(blocks) == 1
        assert blocks[0]["page"] == 2

    def test_empty_pdf_returns_empty(self):
        mock_fitz = MagicMock()
        mock_doc = MagicMock()
        mock_doc.__len__ = MagicMock(return_value=0)
        mock_fitz.open.return_value = mock_doc

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            blocks = _ocr_scanned_pdf(b"empty pdf")

        assert blocks == []


class TestRunExtractOcrFallback:
    def test_scanned_pdf_triggers_paddleocr(self):
        pipeline = ImportPipeline()
        sparse_blocks = [{"page": 1, "block_index": 0, "text": "ab"}]
        ocr_blocks = [{"page": 1, "block_index": 0, "text": "OCR 识别到的完整内容"}]

        with patch(
            "app.features.pipeline_orchestrator._extract_pdf_blocks",
            return_value=sparse_blocks,
        ):
            with patch(
                "app.features.pipeline_orchestrator._ocr_scanned_pdf",
                return_value=ocr_blocks,
            ) as mock_ocr:
                with patch("app.core.config.settings.OCR_ENABLED", True):
                    result = pipeline._run_extract(b"pdf content", "pdf")

        mock_ocr.assert_called_once_with(b"pdf content", pipeline_id="", page_start=1, page_end=None)
        assert result["raw_blocks"] == ocr_blocks
        assert result["extracted"] == 1

    def test_scanned_pdf_ocr_disabled_uses_sparse(self):
        pipeline = ImportPipeline()
        sparse_blocks = [{"page": 1, "block_index": 0, "text": "ab"}]

        with patch(
            "app.features.pipeline_orchestrator._extract_pdf_blocks",
            return_value=sparse_blocks,
        ):
            with patch("app.core.config.settings.OCR_ENABLED", False):
                result = pipeline._run_extract(b"pdf content", "pdf")

        assert result["raw_blocks"] == sparse_blocks

    def test_scanned_pdf_ocr_failure_falls_back(self):
        pipeline = ImportPipeline()
        sparse_blocks = [{"page": 1, "block_index": 0, "text": "x"}]

        with patch(
            "app.features.pipeline_orchestrator._extract_pdf_blocks",
            return_value=sparse_blocks,
        ):
            with patch(
                "app.features.pipeline_orchestrator._ocr_scanned_pdf",
                side_effect=RuntimeError("paddleocr 未安装"),
            ):
                with patch("app.core.config.settings.OCR_ENABLED", True):
                    result = pipeline._run_extract(b"pdf content", "pdf")

        assert result["raw_blocks"] == sparse_blocks

    def test_normal_pdf_no_ocr_triggered(self):
        pipeline = ImportPipeline()
        blocks = [{"page": 1, "block_index": 0, "text": "A" * 200}]

        with patch(
            "app.features.pipeline_orchestrator._extract_pdf_blocks",
            return_value=blocks,
        ):
            result = pipeline._run_extract(b"pdf content", "pdf")

        assert result["raw_blocks"] == blocks
        assert result["extracted"] == 1


# ---------------------------------------------------------------------------
# ImportPipeline — split stage
# ---------------------------------------------------------------------------


class TestImportPipelineSplit:
    def test_fallback_question_created_for_unsplit_text(self):
        pipeline = ImportPipeline()
        normalized_blocks = [
            {"page": 2, "block_index": 0, "normalized_text": "这是一段没有题号的 OCR 文本。"},
            {"page": 3, "block_index": 1, "normalized_text": "仍然需要进入人工审核。"},
        ]

        result = pipeline._run_split(normalized_blocks)

        assert result["split_count"] == 1
        assert result["split_diagnostics"] == {
            "normalized_block_count": 2,
            "text_block_count": 2,
            "raw_question_count": 0,
            "raw_questions_preview": [],
            "failure_reason": "text_present_but_no_question_boundary",
            "fallback_created": True,
        }
        assert result["warnings"] == ["no questions found in document; created low-confidence review item"]
        assert result["raw_questions"] == [{
            "number": 1,
            "raw_question_text": "这是一段没有题号的 OCR 文本。\n仍然需要进入人工审核。",
            "page_start": 2,
            "page_end": 3,
            "has_options": False,
            "option_lines": {},
            "confidence": 0.2,
        }]

    def test_numbered_questions_do_not_use_fallback(self):
        pipeline = ImportPipeline()
        normalized_blocks = [
            {"page": 1, "block_index": 0, "normalized_text": "1. 已编号题目\nA. 选项A\nB. 选项B"},
        ]

        result = pipeline._run_split(normalized_blocks)

        assert result["split_count"] == 1
        assert result["split_diagnostics"] == {
            "normalized_block_count": 1,
            "text_block_count": 1,
            "raw_question_count": 1,
            "raw_questions_preview": [
                {
                    "number": 1,
                    "raw_question_text": "1. 已编号题目\nA. 选项A\nB. 选项B",
                    "page_start": 1,
                    "page_end": 1,
                    "has_options": True,
                    "option_lines": {"A": "选项A", "B": "选项B"},
                    "confidence": 0.9,
                    "section_type": None,
                }
            ],
            "failure_reason": None,
            "fallback_created": False,
        }
        assert result["warnings"] == []
        assert result["raw_questions"][0]["confidence"] != 0.2

    def test_match_uses_separated_structure(self):
        pipeline = ImportPipeline()
        normalized_blocks = [
            {
                "page": 1,
                "block_index": 0,
                "normalized_text": "1. 题目A\nA. 选项A\nB. 选项B\n2. 题目B\nA. 选项A\nB. 选项B",
            },
            {"page": 2, "block_index": 1, "normalized_text": "参考答案：\n1. B\n2. A"},
        ]
        structure = pipeline._run_analyze_structure(normalized_blocks)["structure"]
        split = pipeline._run_split(normalized_blocks, structure=structure)
        result = pipeline._run_match(split["raw_questions"], normalized_blocks, structure=structure)

        assert structure["mode"] == "SEPARATED"
        assert structure["answer_pages"] == [2]
        assert [q["answer"] for q in result["matched"]] == ["B", "A"]
        assert all(q["answer_source"] == "separated" for q in result["matched"])


# ---------------------------------------------------------------------------
# PipelineStage
# ---------------------------------------------------------------------------


class TestPipelineStage:
    def test_sync_run_success(self):
        def add(a, b):
            return a + b

        stage = PipelineStage("test", add)
        result = stage.run(a=1, b=2)

        assert result == 3
        assert stage.status == "completed"
        assert stage.duration_ms >= 0
        assert stage.error is None

    def test_sync_run_failure(self):
        def fail():
            raise ValueError("boom")

        stage = PipelineStage("test", fail)
        with pytest.raises(ValueError, match="boom"):
            stage.run()

        assert stage.status == "failed"
        assert stage.error == "boom"

    def test_async_run_success(self):
        async def add(a, b):
            return a + b

        stage = PipelineStage("test", add)
        result = asyncio.run(stage.run_async(a=1, b=2))

        assert result == 3
        assert stage.status == "completed"

    def test_async_run_with_sync_fn(self):
        def add(a, b):
            return a + b

        stage = PipelineStage("test", add)
        result = asyncio.run(stage.run_async(a=1, b=2))

        assert result == 3
        assert stage.status == "completed"

    def test_async_run_failure(self):
        async def fail():
            raise ValueError("async boom")

        stage = PipelineStage("test", fail)
        with pytest.raises(ValueError, match="async boom"):
            asyncio.run(stage.run_async())

        assert stage.status == "failed"
        assert stage.error == "async boom"

    def test_to_dict_completed(self):
        stage = PipelineStage("extract", lambda: None)
        stage.status = "completed"
        stage.duration_ms = 100

        d = stage.to_dict()
        assert d == {"name": "extract", "status": "completed", "duration_ms": 100, "warnings": []}

    def test_to_dict_failed(self):
        stage = PipelineStage("extract", lambda: None)
        stage.status = "failed"
        stage.error = "something wrong"

        d = stage.to_dict()
        assert d["status"] == "failed"
        assert d["error"] == "something wrong"

    def test_warnings_accumulate(self):
        stage = PipelineStage("test", lambda: None)
        stage.warnings.append("warning 1")
        stage.warnings.append("warning 2")

        d = stage.to_dict()
        assert d["warnings"] == ["warning 1", "warning 2"]


# ---------------------------------------------------------------------------
# ImportPipeline — stage mocks
# ---------------------------------------------------------------------------


class TestImportPipelineRun:
    """Test pipeline orchestration by mocking individual stages."""

    def _make_pipeline(self, **overrides):
        """Create a pipeline with all stages mocked. Rebuilds stages after mocking."""
        pipeline = ImportPipeline(options=overrides.get("options"))
        pipeline._run_extract = MagicMock(return_value={
            "raw_blocks": _make_raw_blocks(3),
            "extracted": 3,
        })
        pipeline._run_normalize_text = MagicMock(return_value={
            "normalized_blocks": _make_normalized_blocks(3),
        })
        pipeline._run_ocr_correction = AsyncMock(return_value={
            "normalized_blocks": _make_normalized_blocks(3),
            "ocr_correction_diagnostics": {"stats": {}, "corrections": [], "skipped_reason": None},
        })
        pipeline._run_split = MagicMock(return_value={
            "raw_questions": _make_raw_questions(3),
            "split_count": 3,
        })
        pipeline._run_match = MagicMock(return_value={
            "matched": _make_matched(3),
            "unmatched": [],
            "matched_count": 3,
        })
        pipeline._run_normalize_schema = MagicMock(return_value={
            "questions": _make_questions(3),
            "normalized_count": 3,
        })
        pipeline._run_repair = MagicMock(return_value={
            "questions": _make_questions(3),
            "repaired_count": 1,
            "unrepaired_count": 0,
            "skipped_count": 2,
            "total_tokens": 500,
        })
        pipeline._run_ai_validation = MagicMock(return_value={
            "questions": _make_questions(3),
            "ai_validation_diagnostics": {"total": 3, "valid": 3, "warnings": 0, "errors": 0},
        })
        pipeline._run_similarity_match = AsyncMock(return_value={
            "questions": _make_questions(3),
            "similarity_match_diagnostics": {"stats": {}, "matches": [], "skipped_reason": None},
        })
        pipeline._run_review = AsyncMock(return_value={
            "batch_id": "REVIEW_test",
            "written": 3,
            "skipped": 0,
            "total": 3,
        })
        # Rebuild stages so PipelineStage objects reference the mocked methods
        pipeline._build_pipeline()
        return pipeline

    def test_full_pipeline_success(self):
        pipeline = self._make_pipeline()

        result = asyncio.run(pipeline.run(
            file_content=b"fake pdf",
            source_type="pdf",
            source_file="test.pdf",
            subject="math2",
            db=_make_mock_db(),
        ))

        assert result["status"] == "completed"
        assert result["stats"]["extracted"] == 3
        assert result["stats"]["split"] == 3
        assert result["stats"]["matched"] == 3
        assert result["stats"]["schema_normalized"] == 3
        assert result["stats"]["repaired"] == 1
        assert result["stats"]["to_review"] == 3
        assert len(result["errors"]) == 0

        # Verify stage ordering
        stage_names = list(result["stages"].keys())
        assert stage_names == ["extract", "normalize_text", "ocr_correction", "analyze_structure", "classify_pages", "split", "match", "normalize_schema", "batch_validation", "batch_dedup", "repair", "ai_validation", "similarity_match", "review"]
        for s in result["stages"].values():
            assert s["status"] == "completed"

    def test_ai_repair_disabled(self):
        pipeline = self._make_pipeline()
        pipeline.options["enable_ai_repair"] = False

        # Rebuild so repair stage is excluded
        pipeline._build_pipeline()

        result = asyncio.run(pipeline.run(
            file_content=b"fake",
            source_type="pdf",
            source_file="test.pdf",
        ))

        stage_names = list(result["stages"].keys())
        assert "repair" not in stage_names
        assert "review" in stage_names

    def test_ai_repair_enabled(self):
        pipeline = self._make_pipeline()
        pipeline.options["enable_ai_repair"] = True

        result = asyncio.run(pipeline.run(
            file_content=b"fake",
            source_type="pdf",
            source_file="test.pdf",
        ))

        stage_names = list(result["stages"].keys())
        assert "repair" in stage_names

    def test_extract_failure_aborts_pipeline(self):
        pipeline = ImportPipeline()
        pipeline._run_extract = MagicMock(side_effect=ValueError("bad file"))

        result = asyncio.run(pipeline.run(
            file_content=b"",
            source_type="pdf",
            source_file="test.pdf",
        ))

        assert result["status"] == "failed"
        assert "extract" in result["errors"][0]
        # Only extract should have run (or failed)
        assert result["stages"]["extract"]["status"] == "failed"

    def test_normalize_text_failure_aborts_pipeline(self):
        pipeline = ImportPipeline()
        pipeline._run_extract = MagicMock(return_value={"raw_blocks": [], "extracted": 0})
        pipeline._run_normalize_text = MagicMock(side_effect=ValueError("text error"))

        result = asyncio.run(pipeline.run(
            file_content=b"x",
            source_type="pdf",
            source_file="test.pdf",
        ))

        assert result["status"] == "failed"
        assert result["stages"]["normalize_text"]["status"] == "failed"

    def test_later_stage_failure_continues_pipeline(self):
        """Match stage failure should not abort — error isolation."""
        pipeline = ImportPipeline()
        pipeline._run_extract = MagicMock(return_value={"raw_blocks": _make_raw_blocks(2), "extracted": 2})
        pipeline._run_normalize_text = MagicMock(return_value={"normalized_blocks": _make_normalized_blocks(2)})
        pipeline._run_split = MagicMock(return_value={"raw_questions": _make_raw_questions(2), "split_count": 2})
        pipeline._run_match = MagicMock(side_effect=ValueError("match error"))
        pipeline._run_normalize_schema = MagicMock(return_value={"questions": [], "normalized_count": 0})
        pipeline._run_review = AsyncMock(return_value={"batch_id": "", "written": 0, "total": 0})

        result = asyncio.run(pipeline.run(
            file_content=b"x",
            source_type="pdf",
            source_file="test.pdf",
        ))

        # Pipeline should continue despite match failure
        assert result["stages"]["match"]["status"] == "failed"
        assert result["stages"]["normalize_schema"]["status"] == "completed"
        assert "match" in result["errors"][0]

    def test_empty_questions_flow(self):
        """Pipeline with no questions found still completes."""
        pipeline = ImportPipeline()
        pipeline._run_extract = MagicMock(return_value={"raw_blocks": [], "extracted": 0})
        pipeline._run_normalize_text = MagicMock(return_value={"normalized_blocks": []})
        pipeline._run_split = MagicMock(return_value={"raw_questions": [], "split_count": 0, "warnings": ["no questions found"]})
        pipeline._run_match = MagicMock(return_value={"matched": [], "unmatched": [], "matched_count": 0})
        pipeline._run_normalize_schema = MagicMock(return_value={"questions": [], "normalized_count": 0})
        pipeline._run_review = AsyncMock(return_value={"batch_id": "", "written": 0, "total": 0})

        result = asyncio.run(pipeline.run(
            file_content=b"x",
            source_type="pdf",
            source_file="empty.pdf",
        ))

        assert result["status"] == "completed"
        assert result["stats"]["split"] == 0
        assert result["stats"]["to_review"] == 0

    def test_review_without_db(self):
        """Review stage should skip gracefully when no db provided."""
        pipeline = ImportPipeline()
        pipeline._run_extract = MagicMock(return_value={"raw_blocks": _make_raw_blocks(1), "extracted": 1})
        pipeline._run_normalize_text = MagicMock(return_value={"normalized_blocks": _make_normalized_blocks(1)})
        pipeline._run_split = MagicMock(return_value={"raw_questions": _make_raw_questions(1), "split_count": 1})
        pipeline._run_match = MagicMock(return_value={"matched": _make_matched(1), "unmatched": [], "matched_count": 1})
        pipeline._run_normalize_schema = MagicMock(return_value={"questions": _make_questions(1), "normalized_count": 1})

        result = asyncio.run(pipeline.run(
            file_content=b"x",
            source_type="pdf",
            source_file="test.pdf",
            db=None,  # no db
        ))

        assert result["status"] == "completed"
        assert result["stages"]["review"]["warnings"] == ["no db session provided, review stage skipped"]

    def test_stage_timing_recorded(self):
        pipeline = self._make_pipeline()

        result = asyncio.run(pipeline.run(
            file_content=b"x",
            source_type="pdf",
            source_file="test.pdf",
        ))

        for stage in result["stages"].values():
            assert stage["duration_ms"] >= 0

    def test_p1a_large_fields_released_between_stages(self):
        """P1-A: stage 间清理大字段，避免 normalized_blocks/raw_questions 等
        随后续 8+ 个阶段一起驻留内存。"""
        pipeline = self._make_pipeline()

        # 用 review 阶段做哨兵：到达 review 时，stage 间应已清理：
        #   - raw_blocks         (在 normalize_text 之后)
        #   - normalized_blocks  (在 match 之后)
        #   - raw_questions / matched / unmatched (在 normalize_schema 之后)
        captured: dict = {}

        async def _capture_review(**kw):
            captured.update(kw)
            return {
                "batch_id": "REVIEW_p1a",
                "written": 3,
                "skipped": 0,
                "total": 3,
            }

        pipeline._run_review = _capture_review
        pipeline._build_pipeline()

        result = asyncio.run(pipeline.run(
            file_content=b"fake pdf",
            source_type="pdf",
            source_file="test.pdf",
            subject="math2",
            db=_make_mock_db(),
        ))

        assert result["status"] == "completed"
        # review 看到的 kwargs 里不应再有大字段
        assert "raw_blocks" not in captured
        assert "normalized_blocks" not in captured
        assert "raw_questions" not in captured
        assert "matched" not in captured
        assert "unmatched" not in captured
        # 但仍然能拿到 questions，pipeline 出口数据完整
        assert isinstance(captured.get("questions"), list)
        assert len(captured["questions"]) == 3
        # stats 里 normalized 计数仍然正确（normalized_block_count 兜底）
        assert result["stats"]["normalized"] == 3

    def test_p1a_stats_normalized_survives_mid_pipeline_failure(self):
        """隐患① 修复：normalize_text 之后任意 stage 失败，stats['normalized']
        仍应反映上一次写入 normalized_blocks 的产物，而不是静默归零。

        修复前 fallback 链是 normalized_count → normalized_block_count → len([])，
        normalized_count 由 normalize_schema 写入，normalized_block_count 由
        match 之后才缓存；analyze_structure 失败时两者都不存在，stats 归零。
        修复后 normalized_blocks 一被写入就同步缓存 count。
        """
        pipeline = self._make_pipeline()
        # analyze_structure 在 normalize_text 之后第一个失败
        pipeline._run_analyze_structure = MagicMock(side_effect=ValueError("structure fail"))
        # 后续阶段也直接失败，避免它们再写入 normalized_blocks 干扰断言
        pipeline._run_classify_pages = MagicMock(side_effect=ValueError("classify fail"))
        pipeline._run_split = MagicMock(side_effect=ValueError("split fail"))
        pipeline._run_match = MagicMock(side_effect=ValueError("match fail"))
        # normalize_schema 也不写 normalized_count，模拟 schema 也未走 happy path
        pipeline._run_normalize_schema = MagicMock(return_value={"questions": []})
        pipeline._build_pipeline()

        result = asyncio.run(pipeline.run(
            file_content=b"fake pdf",
            source_type="pdf",
            source_file="test.pdf",
            subject="math2",
            db=_make_mock_db(),
        ))

        # pipeline 整体被标记 failed
        assert result["status"] == "failed"
        assert result["stages"]["analyze_structure"]["status"] == "failed"
        # 关键断言：ocr_correction 输出 3 个 block，stats['normalized'] 应等于 3
        # 而非修复前的 0（因为 normalized_count 和 normalized_blocks 都缺失）
        assert result["stats"]["normalized"] == 3


# ---------------------------------------------------------------------------
# run_import_pipeline
# ---------------------------------------------------------------------------


class TestRunImportPipeline:
    def test_returns_pipeline_id(self):
        pipeline = ImportPipeline()
        pipeline._run_extract = MagicMock(return_value={"raw_blocks": _make_raw_blocks(1), "extracted": 1})
        pipeline._run_normalize_text = MagicMock(return_value={"normalized_blocks": _make_normalized_blocks(1)})
        pipeline._run_split = MagicMock(return_value={"raw_questions": [], "split_count": 0})
        pipeline._run_match = MagicMock(return_value={"matched": [], "unmatched": [], "matched_count": 0})
        pipeline._run_normalize_schema = MagicMock(return_value={"questions": [], "normalized_count": 0})
        pipeline._run_review = AsyncMock(return_value={"batch_id": "", "written": 0, "total": 0})

        with patch("app.features.pipeline_orchestrator.ImportPipeline", return_value=pipeline):
            result = asyncio.run(run_import_pipeline(
                file_content=b"x",
                source_type="txt",
                source_file="test.txt",
            ))

        assert result["pipeline_id"].startswith("pl_")
        assert "started_at" in result

    def test_txt_source_type(self):
        pipeline = ImportPipeline()
        pipeline._run_extract = MagicMock(return_value={"raw_blocks": _make_raw_blocks(1), "extracted": 1})
        pipeline._run_normalize_text = MagicMock(return_value={"normalized_blocks": _make_normalized_blocks(1)})
        pipeline._run_split = MagicMock(return_value={"raw_questions": [], "split_count": 0})
        pipeline._run_match = MagicMock(return_value={"matched": [], "unmatched": [], "matched_count": 0})
        pipeline._run_normalize_schema = MagicMock(return_value={"questions": [], "normalized_count": 0})
        pipeline._run_review = AsyncMock(return_value={"batch_id": "", "written": 0, "total": 0})

        with patch("app.features.pipeline_orchestrator.ImportPipeline", return_value=pipeline):
            result = asyncio.run(run_import_pipeline(
                file_content=b"plain text",
                source_type="txt",
                source_file="notes.txt",
                subject="exam408",
            ))

        assert result["status"] == "completed"


# ---------------------------------------------------------------------------
# run_pipeline_background + get_pipeline_status
# ---------------------------------------------------------------------------


class TestBackgroundPipeline:
    def test_status_transitions(self):
        pipeline = ImportPipeline()
        pipeline._run_extract = MagicMock(return_value={"raw_blocks": _make_raw_blocks(1), "extracted": 1})
        pipeline._run_normalize_text = MagicMock(return_value={"normalized_blocks": _make_normalized_blocks(1)})
        pipeline._run_split = MagicMock(return_value={"raw_questions": [], "split_count": 0})
        pipeline._run_match = MagicMock(return_value={"matched": [], "unmatched": [], "matched_count": 0})
        pipeline._run_normalize_schema = MagicMock(return_value={"questions": [], "normalized_count": 0})
        pipeline._run_review = AsyncMock(return_value={"batch_id": "", "written": 0, "total": 0})

        pid = "pl_test_001"

        with patch("app.features.pipeline_orchestrator.ImportPipeline", return_value=pipeline):
            asyncio.run(run_pipeline_background(
                pipeline_id=pid,
                file_content=b"x",
                source_type="txt",
                source_file="test.txt",
            ))

        status = asyncio.run(get_pipeline_status(pid))
        assert status is not None
        assert status["pipeline_id"] == pid
        assert status["status"] == "completed"

    def test_background_failure_captured(self):
        """When the pipeline raises, the error should be stored."""
        with patch("app.features.pipeline_orchestrator.run_import_pipeline") as mock_run:
            mock_run.side_effect = RuntimeError("catastrophic failure")

            asyncio.run(run_pipeline_background(
                pipeline_id="pl_fail_001",
                file_content=b"x",
                source_type="txt",
                source_file="test.txt",
            ))

        status = asyncio.run(get_pipeline_status("pl_fail_001"))
        assert status["status"] == "failed"
        assert "catastrophic failure" in status["errors"][0]

    def test_status_not_found(self):
        assert asyncio.run(get_pipeline_status("nonexistent")) is None

    def test_store_pruning(self):
        """Store should not grow unbounded."""
        # Fill store with more than _MAX_STORE_SIZE entries
        for i in range(510):
            _pipeline_store[f"pl_{i}"] = {
                "pipeline_id": f"pl_{i}",
                "status": "completed",
                "started_at": f"2026-05-24T00:{i % 60:02d}:00",
            }

        # Trigger prune by adding one more via background
        pipeline = ImportPipeline()
        pipeline._run_extract = MagicMock(return_value={"raw_blocks": _make_raw_blocks(1), "extracted": 1})
        pipeline._run_normalize_text = MagicMock(return_value={"normalized_blocks": _make_normalized_blocks(1)})
        pipeline._run_split = MagicMock(return_value={"raw_questions": [], "split_count": 0})
        pipeline._run_match = MagicMock(return_value={"matched": [], "unmatched": [], "matched_count": 0})
        pipeline._run_normalize_schema = MagicMock(return_value={"questions": [], "normalized_count": 0})
        pipeline._run_review = AsyncMock(return_value={"batch_id": "", "written": 0, "total": 0})

        with patch("app.features.pipeline_orchestrator.ImportPipeline", return_value=pipeline):
            asyncio.run(run_pipeline_background(
                pipeline_id="pl_new_001",
                file_content=b"x",
                source_type="txt",
                source_file="test.txt",
            ))

        assert len(_pipeline_store) <= 510  # should have been pruned


# ---------------------------------------------------------------------------
# P0-3: store slimming + diagnostics split
# ---------------------------------------------------------------------------


class TestPipelineStoreSlim:
    """主 _pipeline_store 不应再持有 diagnostics（P0-3 内存瘦身）。"""

    def test_set_strips_diagnostics_into_separate_store(self):
        from app.features.pipeline_orchestrator import (
            _pipeline_diagnostics_store,
            _set_pipeline_store,
        )

        pid = "pl_slim_001"
        _pipeline_store.pop(pid, None)
        _pipeline_diagnostics_store.pop(pid, None)

        diagnostics = {
            "split": {"raw_questions_preview": [{"raw_question_text": "x" * 5000}] * 20},
            "ocr_correction": {"corrections": [{"page": i, "text": "y" * 200} for i in range(50)]},
        }
        full_payload = {
            "pipeline_id": pid,
            "status": "completed",
            "source_type": "pdf",
            "stages": {"extract": {"status": "completed"}},
            "stats": {"total": 100},
            "errors": [],
            "started_at": "2026-06-05T00:00:00",
            "diagnostics": diagnostics,
        }
        asyncio.run(_set_pipeline_store(pid, full_payload))

        # 主 store 不能含 diagnostics
        assert "diagnostics" not in _pipeline_store[pid]
        assert _pipeline_store[pid]["pipeline_id"] == pid
        assert _pipeline_store[pid]["stats"] == {"total": 100}

        # diagnostics 走独立 store
        assert pid in _pipeline_diagnostics_store
        assert _pipeline_diagnostics_store[pid] == diagnostics

    def test_status_query_merges_diagnostics_back(self):
        from app.features.pipeline_orchestrator import (
            _pipeline_diagnostics_store,
            _set_pipeline_store,
        )

        pid = "pl_slim_002"
        _pipeline_store.pop(pid, None)
        _pipeline_diagnostics_store.pop(pid, None)

        diagnostics = {"split": {"failure_reason": None}, "structure": {"mode": "exam"}}
        asyncio.run(_set_pipeline_store(pid, {
            "pipeline_id": pid,
            "status": "completed",
            "source_type": "pdf",
            "stages": {},
            "stats": {},
            "errors": [],
            "started_at": "2026-06-05T00:00:00",
            "diagnostics": diagnostics,
        }))

        status = asyncio.run(get_pipeline_status(pid))
        assert status is not None
        assert status["diagnostics"] == diagnostics
        assert status["status"] == "completed"

    def test_prune_removes_diagnostics_alongside_store(self):
        from app.features.pipeline_orchestrator import (
            _MAX_STORE_SIZE,
            _pipeline_diagnostics_store,
            _prune_store,
        )

        # 重置
        _pipeline_store.clear()
        _pipeline_diagnostics_store.clear()

        for i in range(_MAX_STORE_SIZE + 5):
            pid = f"pl_prune_{i:04d}"
            _pipeline_store[pid] = {
                "pipeline_id": pid,
                "status": "completed",
                "started_at": f"2026-06-05T00:00:{i:08d}",
            }
            _pipeline_diagnostics_store[pid] = {"i": i}

        _prune_store()
        # 最旧 5 个应被清除（store + diagnostics 同步）
        assert len(_pipeline_store) == _MAX_STORE_SIZE
        for i in range(5):
            assert f"pl_prune_{i:04d}" not in _pipeline_store
            assert f"pl_prune_{i:04d}" not in _pipeline_diagnostics_store

    def test_status_query_does_not_pollute_main_store(self):
        """get_pipeline_status 必须返回拷贝，不能把 ocr_progress 写进主 store。

        回归保护：之前实现里 get_pipeline_status 直接复用 _pipeline_store[pid]
        引用，对 data["ocr_progress"] 赋值会污染主 store 的白名单契约。
        """
        from app.features.pipeline_orchestrator import (
            _ocr_progress,
            _pipeline_diagnostics_store,
            _PIPELINE_STORE_FIELDS,
            _set_pipeline_store,
        )

        pid = "pl_pollute_001"
        # 隔离前序测试可能塞满的 prune 数据，避免 _set_pipeline_store
        # 内的 _prune_store 把当前用例的新条目反被淘汰。
        _pipeline_store.clear()
        _pipeline_diagnostics_store.clear()
        _ocr_progress.pop(pid, None)

        asyncio.run(_set_pipeline_store(pid, {
            "pipeline_id": pid,
            "status": "running",
            "source_type": "pdf",
            "stages": {},
            "stats": {},
            "errors": [],
            "started_at": "2026-06-05T00:00:00",
        }))

        _ocr_progress[pid] = "32/312 pages"
        try:
            status = asyncio.run(get_pipeline_status(pid))
            assert status is not None
            assert status.get("ocr_progress") == "32/312 pages"

            # 主 store 仍只含白名单字段
            stored = _pipeline_store[pid]
            assert "ocr_progress" not in stored
            assert set(stored.keys()).issubset(set(_PIPELINE_STORE_FIELDS))

            # 修改返回视图不能反污染主 store
            status["status"] = "tampered"
            assert _pipeline_store[pid]["status"] == "running"
        finally:
            _ocr_progress.pop(pid, None)


# ---------------------------------------------------------------------------
# ImportPipeline — _run_repair data flow
# ---------------------------------------------------------------------------


class TestRepairStage:
    def test_combines_repaired_unrepaired_and_skipped(self):
        questions = _make_questions(3)
        # Mark q0 with low confidence
        questions[0]["confidence_score"] = 0.3
        questions[1]["confidence_score"] = 0.4
        questions[2]["confidence_score"] = 0.9

        pipeline = ImportPipeline()
        # Mock repair_questions to return controlled result
        repaired = [{
            "question_index": 0,
            "before": questions[0],
            "after": {**questions[0], "stem": "Repaired stem", "confidence_score": 0.75},
            "repair_actions": ["fixed_stem"],
            "confidence": 0.75,
            "token_used": 100,
        }]
        unrepaired = [{"question_index": 1, "reason": "ai_failed"}]
        skipped = [{"question_index": 2, "reason": "above_threshold", "confidence": 0.9}]

        with patch("app.features.pipeline_orchestrator.repair_questions", new_callable=AsyncMock, return_value={
            "repaired": repaired,
            "unrepaired": unrepaired,
            "skipped": skipped,
            "stats": {"total_candidates": 3, "repaired": 1, "unrepaired": 1, "skipped": 1, "total_tokens": 100},
        }):
            result = asyncio.run(pipeline._run_repair(questions=questions, options={}))

        assert result["repaired_count"] == 1
        assert result["unrepaired_count"] == 1
        assert result["skipped_count"] == 1
        assert result["total_tokens"] == 100
        assert len(result["questions"]) == 3
        # Repaired question has new stem
        assert result["questions"][0]["stem"] == "Repaired stem"
        assert result["questions"][0]["confidence_score"] == 0.75

    def test_warnings_for_unrepaired(self):
        questions = _make_questions(1)
        questions[0]["confidence_score"] = 0.3

        pipeline = ImportPipeline()
        with patch("app.features.pipeline_orchestrator.repair_questions", new_callable=AsyncMock, return_value={
            "repaired": [],
            "unrepaired": [{"question_index": 0, "reason": "ai_unavailable"}],
            "skipped": [],
            "stats": {"total_candidates": 1, "repaired": 0, "unrepaired": 1, "skipped": 0, "total_tokens": 0},
        }):
            result = asyncio.run(pipeline._run_repair(questions=questions, options={}))

        assert "unrepaired" in result["warnings"][0]
        assert len(result["questions"]) == 1
        assert result["questions"][0]["confidence_score"] == 0.3  # original preserved


# ---------------------------------------------------------------------------
# ImportPipeline — options passthrough
# ---------------------------------------------------------------------------


class TestPipelineOptions:
    def test_confidence_threshold_passed_to_repair(self):
        questions = _make_questions(2)

        pipeline = ImportPipeline(options={"enable_ai_repair": True, "confidence_threshold": 0.8})

        with patch("app.features.pipeline_orchestrator.repair_questions", new_callable=AsyncMock) as mock_repair:
            mock_repair.return_value = {
                "repaired": [],
                "unrepaired": [],
                "skipped": [{"question_index": 0, "reason": "above_threshold", "confidence": 0.85},
                           {"question_index": 1, "reason": "above_threshold", "confidence": 0.9}],
                "stats": {"total_candidates": 2, "repaired": 0, "unrepaired": 0, "skipped": 2, "total_tokens": 0},
            }
            result = asyncio.run(pipeline._run_repair(questions=questions, options={"confidence_threshold": 0.8}))

            # Check repair_questions was called with threshold in config
            call_config = mock_repair.call_args[0][1]
            assert call_config["confidence_threshold"] == 0.8
            assert call_config["enabled"] is True
