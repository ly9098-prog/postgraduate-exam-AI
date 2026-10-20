"""Stage 9 OCR 增强服务 — 单元测试。AI 调用和 PyMuPDF 全部 mock。"""
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

try:
    import paddleocr  # noqa: F401
except ImportError:
    pytest.skip(
        "跳过: paddleocr 未安装，OCR 测试需要 paddleocr 依赖",
        allow_module_level=True,
    )







# ============================================================
# is_ocr_enabled
# ============================================================


class TestIsOcrEnabled:
    def test_enabled_via_settings(self):
        with patch("app.features.ocr_service.settings") as mock_settings:
            mock_settings.OCR_ENABLED = True
            from app.features.ocr_service import is_ocr_enabled
            assert is_ocr_enabled() is True

    def test_disabled_via_settings(self):
        with patch("app.features.ocr_service.settings") as mock_settings:
            mock_settings.OCR_ENABLED = False
            from app.features.ocr_service import is_ocr_enabled
            assert is_ocr_enabled() is False

    def test_falsy_values(self):
        with patch("app.features.ocr_service.settings") as mock_settings:
            mock_settings.OCR_ENABLED = 0
            from app.features.ocr_service import is_ocr_enabled
            assert is_ocr_enabled() is False


# ============================================================
# is_scanned_pdf
# ============================================================


class TestIsScannedPdf:
    def test_scanned_pdf_low_text(self):
        """文本极少 → 判定为扫描版。"""
        mock_fitz = MagicMock()
        mock_doc = MagicMock()
        mock_page = MagicMock()
        mock_page.get_text.return_value = "  "  # 仅空白
        mock_doc.__iter__.return_value = [mock_page]
        mock_doc.__enter__ = MagicMock(return_value=mock_doc)
        mock_doc.__exit__ = MagicMock(return_value=False)
        mock_fitz.open.return_value = mock_doc

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            from app.features.ocr_service import is_scanned_pdf
            assert is_scanned_pdf(b"fake pdf content") is True

    def test_text_pdf_not_scanned(self):
        """文本充足 → 不是扫描版。"""
        mock_fitz = MagicMock()
        mock_doc = MagicMock()
        mock_page = MagicMock()
        mock_page.get_text.return_value = "这是正常的文本内容，包含大量可复制的文字。" * 10
        mock_doc.__iter__.return_value = [mock_page]
        mock_doc.__enter__ = MagicMock(return_value=mock_doc)
        mock_doc.__exit__ = MagicMock(return_value=False)
        mock_fitz.open.return_value = mock_doc

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            from app.features.ocr_service import is_scanned_pdf
            assert is_scanned_pdf(b"fake pdf content") is False

    def test_custom_threshold(self):
        """自定义阈值。"""
        mock_fitz = MagicMock()
        mock_doc = MagicMock()
        mock_page = MagicMock()
        mock_page.get_text.return_value = "短文本"  # 3 chars
        mock_doc.__iter__.return_value = [mock_page]
        mock_doc.__enter__ = MagicMock(return_value=mock_doc)
        mock_doc.__exit__ = MagicMock(return_value=False)
        mock_fitz.open.return_value = mock_doc

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            from app.features.ocr_service import is_scanned_pdf
            # 默认阈值 100 → 判定为扫描版
            assert is_scanned_pdf(b"fake") is True
            # 自定义阈值 2 → 不判定为扫描版
            assert is_scanned_pdf(b"fake", min_text_length=2) is False

    def test_no_fitz_returns_false(self):
        """PyMuPDF 未安装 → 返回 False（不阻断流程）。"""
        with patch.dict(sys.modules, {"fitz": None}):
            # Remove fitz from sys.modules to trigger ImportError
            pass
        # 如果 fitz 不存在于 sys.modules，import fitz 会抛 ImportError
        with patch.dict(sys.modules):
            sys.modules.pop("fitz", None)
            from app.features.ocr_service import is_scanned_pdf
            assert is_scanned_pdf(b"fake") is False

    def test_fitz_open_exception(self):
        """PyMuPDF 打开失败 → 返回 False。"""
        mock_fitz = MagicMock()
        mock_fitz.open.side_effect = Exception("corrupt PDF")

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            from app.features.ocr_service import is_scanned_pdf
            assert is_scanned_pdf(b"corrupt") is False

    def test_multi_page_scanned(self):
        """多页 PDF，所有页文本都很少。"""
        mock_fitz = MagicMock()
        mock_doc = MagicMock()
        pages = []
        for _ in range(5):
            p = MagicMock()
            p.get_text.return_value = ""
            pages.append(p)
        mock_doc.__iter__.return_value = pages
        mock_doc.__enter__ = MagicMock(return_value=mock_doc)
        mock_doc.__exit__ = MagicMock(return_value=False)
        mock_fitz.open.return_value = mock_doc

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            from app.features.ocr_service import is_scanned_pdf
            assert is_scanned_pdf(b"fake") is True

    def test_multi_page_has_text(self):
        """多页 PDF，总文本充足。"""
        mock_fitz = MagicMock()
        mock_doc = MagicMock()
        pages = []
        for _ in range(10):
            p = MagicMock()
            p.get_text.return_value = "正常文本内容。" * 5  # ~30 chars per page
            pages.append(p)
        mock_doc.__iter__.return_value = pages
        mock_doc.__enter__ = MagicMock(return_value=mock_doc)
        mock_doc.__exit__ = MagicMock(return_value=False)
        mock_fitz.open.return_value = mock_doc

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            from app.features.ocr_service import is_scanned_pdf
            assert is_scanned_pdf(b"fake") is False


# ============================================================
# _call_ocr_api
# ============================================================


# ============================================================
# OCRFixRouter adapter chaining tests (replaces old _call_ocr_api / ocr_fallback tests)
# ============================================================


@pytest.fixture
def mock_vl_adapter():
    """Fixture: mock PaddleOCRVLAdapter that always succeeds."""
    adapter = MagicMock()
    # fix is async — use AsyncMock for the coroutine
    adapter.fix = AsyncMock()
    result = MagicMock()
    result.fixed_text = "识别出的题目文字内容 A. 选项1 B. 选项2 C. 选项3 D. 选项4"
    result.confidence = 0.92
    result.model_used = "paddleocr-vl"
    result.risk_flags = []
    result.safety = None
    result.source = "paddleocr-vl"
    result.raw_response = None
    adapter.fix.return_value = result
    return adapter


@pytest.fixture
def mock_deepseek_adapter():
    """Fixture: mock DeepSeek adapter that always succeeds."""
    adapter = MagicMock()
    adapter.fix = AsyncMock()
    result = MagicMock()
    result.fixed_text = "DeepSeek 修正的文字 A. 选项1 B. 选项2 C. 选项3 D. 选项4"
    result.confidence = 0.85
    result.model_used = "deepseek"
    result.risk_flags = []
    result.safety = None
    result.source = "deepseek"
    result.raw_response = None
    adapter.fix.return_value = result
    return adapter


@pytest.fixture
def mock_vl_unsafe_adapter():
    """Fixture: mock PaddleOCRVLAdapter returning collapsed text rejected by safety gate.

    The output is dramatically shorter than the input, which triggers the
    ``length_collapse`` check in ``safe_accept_ai_result``.
    Used to verify the router rejects unsafe candidates.
    """
    adapter = MagicMock()
    adapter.fix = AsyncMock()
    result = MagicMock()
    result.fixed_text = "短"
    result.confidence = 0.95
    result.model_used = "paddleocr-vl"
    result.risk_flags = ["length_collapse"]
    result.safety = None
    result.source = "paddleocr-vl"
    result.raw_response = None
    adapter.fix.return_value = result
    return adapter


@pytest.fixture
def mock_empty_adapter():
    """Fixture: mock adapter returning empty result."""
    adapter = MagicMock()
    adapter.fix = AsyncMock()
    result = MagicMock()
    result.fixed_text = ""
    result.confidence = 0.0
    result.model_used = "paddleocr-vl"
    result.source = "paddleocr-vl"
    result.raw_response = None
    adapter.fix.return_value = result
    return adapter


@pytest.fixture
def mock_failing_adapter():
    """Fixture: mock adapter that raises an exception."""
    adapter = MagicMock()
    adapter.fix = AsyncMock()
    adapter.fix.side_effect = Exception("API connection failed")
    return adapter


class TestOCRFixRouter:
    """Test OCRFixRouter adapter chaining — replaces old _call_ocr_api / ocr_fallback tests.

    Adapters are injected directly via OCRFixRouter(adapters={...}) so the
    lazy _get_adapter path is bypassed and we can test chaining logic in isolation.
    DeepSeek-backed test doubles use the canonical "openai-compatible" chain key.
    """

    @pytest.mark.asyncio
    async def test_vl_success_routes_to_no_deepseek(self, mock_vl_adapter):
        """VL adapter succeeds → validator accepts → no further adapters called."""
        mock_deepseek = MagicMock()
        mock_deepseek.fix = AsyncMock()
        from app.features.ocr_fix.router import OCRFixRouter

        router = OCRFixRouter(adapters={
            "paddleocr-vl": mock_vl_adapter,
            "openai-compatible": mock_deepseek,
        })
        router.configure({"ocr_fix_strategy": "auto"})
        result = await router.fix(
            image=b"fake-image",
            ocr_text="识别出的题目文字内容 A. 选项1 B. 选项2 C. 选项3 D. 选项4",
            context={"page_num": 1, "filename": "test.png"},
        )

        assert result is not None
        assert result.fixed_text is not None
        assert "题目文字内容" in result.fixed_text
        assert result.model_used == "paddleocr-vl"
        mock_vl_adapter.fix.assert_awaited_once()
        mock_deepseek.fix.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_vl_exception_falls_through_to_deepseek(self, mock_failing_adapter, mock_deepseek_adapter):
        """VL adapter raises → router continues to DeepSeek adapter."""
        from app.features.ocr_fix.router import OCRFixRouter

        router = OCRFixRouter(adapters={
            "paddleocr-vl": mock_failing_adapter,
            "openai-compatible": mock_deepseek_adapter,
        })
        # Use auto strategy to enable full chain
        router.configure({"ocr_fix_strategy": "auto"})
        result = await router.fix(
            image=b"fake-image",
            ocr_text="DeepSeek 修正的文字 A. 选项1 B. 选项2 C. 选项3 D. 选项4",
            context={"page_num": 1, "filename": "test.png"},
        )

        assert result is not None
        assert result.fixed_text is not None
        assert "DeepSeek" in result.fixed_text
        mock_failing_adapter.fix.assert_awaited_once()
        mock_deepseek_adapter.fix.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_vl_empty_result_falls_through_to_deepseek(self, mock_empty_adapter, mock_deepseek_adapter):
        """VL adapter returns empty → router continues to DeepSeek adapter."""
        from app.features.ocr_fix.router import OCRFixRouter

        router = OCRFixRouter(adapters={
            "paddleocr-vl": mock_empty_adapter,
            "openai-compatible": mock_deepseek_adapter,
        })
        router.configure({"ocr_fix_strategy": "auto"})
        result = await router.fix(
            image=b"fake-image",
            ocr_text="DeepSeek 修正的文字 A. 选项1 B. 选项2 C. 选项3 D. 选项4",
            context={"page_num": 1, "filename": "test.png"},
        )

        assert result is not None
        assert result.fixed_text is not None
        assert "DeepSeek" in result.fixed_text

    @pytest.mark.asyncio
    async def test_vl_unsafe_rejected_falls_through_to_deepseek(
        self, mock_vl_unsafe_adapter, mock_deepseek_adapter,
    ):
        """VL returns collapsed text → safety gate rejects → falls through to DeepSeek."""
        from app.features.ocr_fix.router import OCRFixRouter

        router = OCRFixRouter(adapters={
            "paddleocr-vl": mock_vl_unsafe_adapter,
            "openai-compatible": mock_deepseek_adapter,
        })
        router.configure({"ocr_fix_strategy": "auto"})
        result = await router.fix(
            image=b"fake-image",
            ocr_text="这是一段较长的OCR识别文本包含选项A选项B选项C选项D需要校验完整内容",
            context={"page_num": 1, "filename": "test.png"},
        )

        assert result is not None
        assert result.fixed_text is not None
        # DeepSeek should be the accepted source
        assert "DeepSeek" in result.fixed_text or "修正" in result.fixed_text
        mock_vl_unsafe_adapter.fix.assert_awaited_once()
        mock_deepseek_adapter.fix.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_vl_and_deepseek_both_rejected_rule_fallback(
        self, mock_vl_unsafe_adapter,
    ):
        """VL and DeepSeek both unsafe → rule fallback or original returned."""
        mock_deepseek_unsafe = MagicMock()
        mock_deepseek_unsafe.fix = AsyncMock()
        ds_result = MagicMock()
        ds_result.fixed_text = "短"
        ds_result.confidence = 0.85
        ds_result.model_used = "deepseek"
        ds_result.risk_flags = ["length_collapse"]
        ds_result.safety = None
        ds_result.source = "deepseek"
        ds_result.raw_response = None
        mock_deepseek_unsafe.fix.return_value = ds_result

        mock_rule = MagicMock()
        mock_rule.fix = AsyncMock()
        rule_result = MagicMock()
        rule_result.fixed_text = "Rule fallback text A. 选项1 B. 选项2"
        rule_result.confidence = 0.6
        rule_result.model_used = "rule_fallback"
        rule_result.risk_flags = []
        rule_result.safety = None
        rule_result.source = "rule_fallback"
        rule_result.raw_response = None
        mock_rule.fix.return_value = rule_result

        from app.features.ocr_fix.router import OCRFixRouter

        router = OCRFixRouter(adapters={
            "paddleocr-vl": mock_vl_unsafe_adapter,
            "openai-compatible": mock_deepseek_unsafe,
            "rule_fallback": mock_rule,
        })
        router.configure({"ocr_fix_strategy": "auto"})
        result = await router.fix(
            image=b"fake-image",
            ocr_text="这是一段较长的OCR识别文本包含选项A选项B选项C选项D需要校验完整内容",
            context={"page_num": 1, "filename": "test.png"},
        )

        assert result is not None
        # Rule fallback should be used (or original if rule also rejected)
        assert result.fixed_text is not None
        mock_rule.fix.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_all_adapters_fail_rule_fallback(self, mock_failing_adapter):
        """VL and DeepSeek both fail → Rule fallback produces result."""
        mock_rule = MagicMock()
        mock_rule.fix = AsyncMock()
        rule_result = MagicMock()
        rule_result.fixed_text = "Rule fallback text A. 选项1 B. 选项2 C. 选项3 D. 选项4"
        rule_result.confidence = 0.6
        rule_result.model_used = "rule_fallback"
        rule_result.source = "rule_fallback"
        rule_result.raw_response = None
        mock_rule.fix.return_value = rule_result

        from app.features.ocr_fix.router import OCRFixRouter

        router = OCRFixRouter(adapters={
            "paddleocr-vl": mock_failing_adapter,
            "openai-compatible": mock_failing_adapter,
            "rule_fallback": mock_rule,
        })
        router.configure({"ocr_fix_strategy": "auto"})
        result = await router.fix(
            image=b"fake-image",
            ocr_text="Rule fallback text A. 选项1 B. 选项2 C. 选项3 D. 选项4",
            context={"page_num": 1, "filename": "test.png"},
        )

        assert result is not None
        assert result.fixed_text is not None
        assert "Rule" in result.fixed_text or result.model_used == "rule_fallback"

    @pytest.mark.asyncio
    async def test_vl_success_no_deepseek_called(self, mock_vl_adapter, mock_deepseek_adapter):
        """Validator accepts VL → DeepSeek is NOT called (performance safeguard)."""
        from app.features.ocr_fix.router import OCRFixRouter

        router = OCRFixRouter(adapters={
            "paddleocr-vl": mock_vl_adapter,
            "openai-compatible": mock_deepseek_adapter,
        })
        router.configure({"ocr_fix_strategy": "auto"})
        result = await router.fix(
            image=b"fake-image",
            ocr_text="识别出的题目文字内容 A. 选项1 B. 选项2 C. 选项3 D. 选项4",
            context={"page_num": 1, "filename": "test.png"},
        )

        assert result is not None
        mock_vl_adapter.fix.assert_awaited_once()
        mock_deepseek_adapter.fix.assert_not_awaited()


# ============================================================
# reserved interfaces
# ============================================================


class TestReservedInterfaces:
    def test_ocr_math_formula_not_implemented(self):
        from app.features.ocr_service import ocr_math_formula
        with pytest.raises(NotImplementedError, match="暂未实现"):
            ocr_math_formula(b"fake")

    def test_ocr_table_not_implemented(self):
        from app.features.ocr_service import ocr_table
        with pytest.raises(NotImplementedError, match="暂未实现"):
            ocr_table(b"fake")


# ============================================================
# pipeline integration — _run_extract OCR trigger
# ============================================================


class TestPipelineOcrIntegration:
    def test_extract_triggers_ocr_for_scanned_pdf(self):
        """PDF 文本 < 100 字符且 OCR 开启 → 触发 PaddleOCR fallback。"""
        from app.features.pipeline_orchestrator import ImportPipeline

        # 模拟极短文本的 PDF blocks
        short_blocks = [{"page": 1, "block_index": 0, "text": "  "}]

        pipeline = ImportPipeline()
        pipeline._build_pipeline()

        # mock 内部函数
        with patch.object(pipeline, "_run_extract", wraps=pipeline._run_extract), \
             patch(
                 "app.features.pipeline_orchestrator._extract_pdf_blocks",
                 return_value=short_blocks,
             ), \
             patch("app.core.config.settings.OCR_ENABLED", True), \
             patch(
                 "app.features.pipeline_orchestrator._ocr_scanned_pdf",
                 return_value=[
                     {"page": 1, "block_index": 0, "text": "OCR 识别的题目 1"},
                     {"page": 1, "block_index": 1, "text": "OCR 识别的题目 2"},
                 ],
             ) as mock_ocr:
            result = pipeline._run_extract(
                file_content=b"fake pdf", source_type="pdf",
            )

        # OCR fallback 被调用了
        mock_ocr.assert_called_once()
        assert result["extracted"] == 2
        assert "OCR 识别" in result["raw_blocks"][0]["text"]

    def test_extract_skips_ocr_for_text_pdf(self):
        """PDF 文本充足 → 不触发 OCR。"""
        from app.features.pipeline_orchestrator import ImportPipeline

        text_blocks = [
            {"page": 1, "block_index": 0, "text": "正常文本内容。" * 20},
        ]

        pipeline = ImportPipeline()
        pipeline._build_pipeline()

        with patch(
            "app.features.pipeline_orchestrator._extract_pdf_blocks",
            return_value=text_blocks,
        ), patch(
            "app.features.ocr_service.ocr_fallback",
        ) as mock_ocr:
            result = pipeline._run_extract(
                file_content=b"fake pdf", source_type="pdf",
            )

        # OCR fallback 未被调用
        mock_ocr.assert_not_called()
        assert result["extracted"] == 1

    def test_extract_skips_ocr_when_disabled(self):
        """OCR_ENABLED=False → 不触发 OCR，即使文本很短。"""
        from app.features.pipeline_orchestrator import ImportPipeline

        short_blocks = [{"page": 1, "block_index": 0, "text": ""}]

        pipeline = ImportPipeline()
        pipeline._build_pipeline()

        with patch(
            "app.features.pipeline_orchestrator._extract_pdf_blocks",
            return_value=short_blocks,
        ), patch(
            "app.features.ocr_service.is_ocr_enabled",
            return_value=False,
        ), patch(
            "app.features.ocr_service.ocr_fallback",
        ) as mock_ocr:
            result = pipeline._run_extract(
                file_content=b"fake pdf", source_type="pdf",
            )

        mock_ocr.assert_not_called()
        assert result["extracted"] == 1

    def test_extract_ocr_failure_graceful(self):
        """OCR fallback 抛异常 → 保留原始 blocks，不阻断 pipeline。"""
        from app.features.pipeline_orchestrator import ImportPipeline

        short_blocks = [{"page": 1, "block_index": 0, "text": "  "}]

        pipeline = ImportPipeline()
        pipeline._build_pipeline()

        with patch(
            "app.features.pipeline_orchestrator._extract_pdf_blocks",
            return_value=short_blocks,
        ), patch(
            "app.features.ocr_service.is_ocr_enabled",
            return_value=True,
        ), patch(
            "app.features.ocr_service.ocr_fallback",
            side_effect=RuntimeError("OCR 全部失败"),
        ):
            result = pipeline._run_extract(
                file_content=b"fake pdf", source_type="pdf",
            )

        # 应该保留原始 blocks（即使文本很少）
        assert result["extracted"] == 1
        assert result["raw_blocks"] == short_blocks

    def test_extract_txt_no_ocr(self):
        """纯文本文件不触发 OCR。"""
        from app.features.pipeline_orchestrator import ImportPipeline

        pipeline = ImportPipeline()
        pipeline._build_pipeline()

        with patch(
            "app.features.pipeline_orchestrator._extract_text_blocks",
            return_value=[{"page": 1, "block_index": 0, "text": "text"}],
        ):
            result = pipeline._run_extract(
                file_content=b"hello world", source_type="txt",
            )

        assert result["extracted"] == 1
