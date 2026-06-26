"""Stage 9 OCR 增强服务 — 单元测试。AI 调用和 PyMuPDF 全部 mock。"""
import sys
from contextlib import ExitStack
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# numpy is required by image preparation functions in ocr_service.
# It is listed in requirements-ocr.txt; skip affected tests if absent.
try:
    import numpy  # noqa: F401
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False


# ============================================================
# ocr_image / dependency handling
# ============================================================


class TestServiceOcrImageDependencyHandling:
    def test_missing_paddleocr_raises_clear_error(self):
        """缺少 paddleocr 时应暴露明确依赖错误，而不是误报未识别到文本。"""
        from app.services import ocr_service

        with patch.object(ocr_service.settings, "OCR_ENABLED", True), patch.object(
            ocr_service,
            "_ocr_instance",
            None,
        ), patch.dict(sys.modules, {"paddleocr": None}):
            with pytest.raises(RuntimeError, match="OCR 依赖未安装：paddleocr"):
                ocr_service.ocr_image(b"fake image")

    def test_ocr_pages_with_boxes_propagates_dependency_error(self):
        """缺少 paddleocr 时，带框接口应容错返回空文本而非抛异常。"""
        from app.services import ocr_service

        with patch.object(ocr_service.settings, "OCR_ENABLED", True), patch.object(
            ocr_service,
            "_ocr_instance",
            None,
        ), patch.dict(sys.modules, {"paddleocr": None}):
            result = ocr_service.ocr_pages_with_boxes([(1, b"fake image")])
            assert result[1].text == ""
            assert result[1].boxes == []


# ============================================================
# _prepare_ocr_image
# ============================================================


@pytest.mark.skipif(not _HAS_NUMPY, reason="numpy not installed (requirements-ocr.txt)")
class TestPrepareOcrImage:
    def test_prepare_ocr_image_applies_exif_transpose_and_returns_rgb(self):
        from PIL import Image
        from app.services.ocr_service import _prepare_ocr_image

        image = Image.new("RGB", (1200, 800), "white")
        exif = Image.Exif()
        exif[274] = 6
        buf = BytesIO()
        image.save(buf, format="JPEG", exif=exif)

        prepared = _prepare_ocr_image(buf.getvalue())

        assert prepared.mode == "RGB"
        assert prepared.size == (1500, 2250)

    def test_prepare_ocr_image_upscales_small_image_within_max_side(self):
        from PIL import Image
        from app.services.ocr_service import _OCR_MAX_SIDE, _prepare_ocr_image

        image = Image.new("RGB", (500, 800), "white")
        buf = BytesIO()
        image.save(buf, format="PNG")

        prepared = _prepare_ocr_image(buf.getvalue())

        assert prepared.mode == "RGB"
        assert prepared.size[0] == 1500
        assert max(prepared.size) <= _OCR_MAX_SIDE

    def test_crop_blank_margins_keeps_blank_image_safe(self):
        from PIL import Image
        from app.services.ocr_service import _crop_blank_margins

        image = Image.new("RGB", (800, 600), "white")

        cropped = _crop_blank_margins(image)

        assert cropped.size == image.size

    def test_crop_blank_margins_removes_large_white_border(self):
        from PIL import Image, ImageDraw
        from app.services.ocr_service import _crop_blank_margins

        image = Image.new("RGB", (1000, 800), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((250, 200, 750, 600), fill="black")

        cropped = _crop_blank_margins(image)

        assert cropped.size[0] < image.size[0]
        assert cropped.size[1] < image.size[1]
        assert cropped.size[0] > 500
        assert cropped.size[1] > 400


@pytest.mark.skipif(not _HAS_NUMPY, reason="numpy not installed (requirements-ocr.txt)")
class TestOcrRotationAndOrdering:
    @staticmethod
    def _ocr_line(text: str, bbox: list[list[int]], conf: float = 0.9):
        return [bbox, [text, conf]]

    def test_rotation_candidates_skip_when_initial_score_good(self):
        from PIL import Image
        from app.services import ocr_service

        image = Image.new("RGB", (1200, 800), "white")
        good_result = [[
            self._ocr_line("1. 这是一道测试题目，包含足够多的文字", [[0, 0], [900, 0], [900, 20], [0, 20]]),
            self._ocr_line("A. 选项一 B. 选项二 C. 选项三 D. 选项四", [[0, 30], [900, 30], [900, 50], [0, 50]]),
            self._ocr_line("解析文本继续提供有效字符", [[0, 60], [900, 60], [900, 80], [0, 80]]),
        ]]
        mock_ocr = MagicMock()
        mock_ocr.ocr.return_value = good_result

        with patch.object(ocr_service, "_prepare_ocr_image", return_value=image):
            candidate = ocr_service._ocr_with_rotation_candidates(mock_ocr, b"image")

        assert candidate.result == good_result
        assert candidate.image_size == image.size
        assert mock_ocr.ocr.call_count == 1

    def test_rotation_candidates_use_better_rotated_result(self):
        from PIL import Image
        from app.services import ocr_service

        image = Image.new("RGB", (1200, 800), "white")
        bad_result = [[self._ocr_line("?", [[0, 0], [10, 0], [10, 10], [0, 10]], 0.2)]]
        rotated_result = [[
            self._ocr_line("1. 旋转后识别出足够多文本内容", [[0, 0], [700, 0], [700, 20], [0, 20]]),
            self._ocr_line("A. 选项一", [[0, 30], [300, 30], [300, 50], [0, 50]]),
            self._ocr_line("B. 选项二", [[0, 60], [300, 60], [300, 80], [0, 80]]),
        ]]
        mock_ocr = MagicMock()
        mock_ocr.ocr.side_effect = [bad_result, rotated_result, bad_result, bad_result]

        with patch.object(ocr_service, "_prepare_ocr_image", return_value=image):
            candidate = ocr_service._ocr_with_rotation_candidates(mock_ocr, b"image")

        assert candidate.result == rotated_result
        assert candidate.image_size == (800, 1200)
        assert mock_ocr.ocr.call_count == 4

    def test_rotation_candidates_fallback_to_raw_image_on_runtime_error(self):
        from PIL import Image
        from app.services import ocr_service

        prepared = Image.new("RGB", (1200, 800), "white")
        raw = Image.new("RGB", (900, 600), "white")
        raw_result = [[self._ocr_line("1. 原图 OCR 文本", [[0, 0], [300, 0], [300, 20], [0, 20]])]]
        mock_ocr = MagicMock()
        mock_ocr.ocr.side_effect = [RuntimeError("could not execute a primitive"), raw_result]

        with patch.object(ocr_service, "_prepare_ocr_image", return_value=prepared), patch.object(
            ocr_service,
            "_load_ocr_image",
            return_value=raw,
        ):
            candidate = ocr_service._ocr_with_rotation_candidates(mock_ocr, b"image")

        assert candidate.result == raw_result
        assert candidate.image_size == raw.size
        assert mock_ocr.ocr.call_count == 2

    def test_ocr_pages_converts_page_exception_to_empty_text(self):
        from app.services import ocr_service

        with patch.object(ocr_service, "_ocr_one_page", side_effect=RuntimeError("could not execute a primitive")):
            result = ocr_service.ocr_pages([(247, b"png")])

        assert result == {247: ""}

    def test_single_column_order_uses_top_then_left(self):
        from app.services.ocr_service import _order_ocr_lines_reading_order

        lines = [
            {"text": "second", "cx": 20, "cy": 50, "width": 100, "bbox": [0, 40, 100, 60]},
            {"text": "first", "cx": 30, "cy": 10, "width": 100, "bbox": [0, 0, 100, 20]},
        ]

        ordered = _order_ocr_lines_reading_order(lines, 1000, 800)

        assert [line["text"] for line in ordered] == ["first", "second"]

    def test_two_column_order_reads_left_column_before_right(self):
        from app.services.ocr_service import _order_ocr_lines_reading_order

        lines = []
        for idx, y in enumerate((100, 140, 180), start=1):
            lines.append({"text": f"L{idx}", "cx": 150, "cy": y, "width": 200, "bbox": [50, y - 10, 250, y + 10]})
            lines.append({"text": f"R{idx}", "cx": 750, "cy": y, "width": 200, "bbox": [650, y - 10, 850, y + 10]})

        ordered = _order_ocr_lines_reading_order(lines, 1000, 800)

        assert [line["text"] for line in ordered] == ["L1", "L2", "L3", "R1", "R2", "R3"]

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
# _pdf_to_images
# ============================================================


class TestPdfToImages:
    def test_single_page(self):
        mock_fitz = MagicMock()
        mock_doc = MagicMock()
        mock_page = MagicMock()
        mock_pix = MagicMock()
        mock_pix.tobytes.return_value = b"fake-png-data"
        mock_page.get_pixmap.return_value = mock_pix
        mock_doc.__iter__.return_value = [mock_page]
        mock_doc.__enter__ = MagicMock(return_value=mock_doc)
        mock_doc.__exit__ = MagicMock(return_value=False)
        mock_fitz.open.return_value = mock_doc

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            from app.features.ocr_service import _pdf_to_images
            images = _pdf_to_images(b"fake pdf")

        assert len(images) == 1
        assert images[0]["page"] == 1
        assert images[0]["image"] == b"fake-png-data"
        assert images[0]["format"] == "png"

    def test_multi_page(self):
        mock_fitz = MagicMock()
        mock_doc = MagicMock()
        pages = []
        for _ in range(3):
            p = MagicMock()
            pix = MagicMock()
            pix.tobytes.return_value = b"png-data"
            p.get_pixmap.return_value = pix
            pages.append(p)
        mock_doc.__iter__.return_value = pages
        mock_doc.__enter__ = MagicMock(return_value=mock_doc)
        mock_doc.__exit__ = MagicMock(return_value=False)
        mock_fitz.open.return_value = mock_doc

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            from app.features.ocr_service import _pdf_to_images
            images = _pdf_to_images(b"fake pdf")

        assert len(images) == 3
        assert [img["page"] for img in images] == [1, 2, 3]

    def test_custom_dpi(self):
        mock_fitz = MagicMock()
        mock_doc = MagicMock()
        mock_page = MagicMock()
        mock_pix = MagicMock()
        mock_pix.tobytes.return_value = b"png"
        mock_page.get_pixmap.return_value = mock_pix
        mock_doc.__iter__.return_value = [mock_page]
        mock_doc.__enter__ = MagicMock(return_value=mock_doc)
        mock_doc.__exit__ = MagicMock(return_value=False)
        mock_fitz.open.return_value = mock_doc

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            from app.features.ocr_service import _pdf_to_images
            _pdf_to_images(b"fake", dpi=150)
            mock_page.get_pixmap.assert_called_once_with(dpi=150)

    def test_empty_pdf_raises(self):
        mock_fitz = MagicMock()
        mock_doc = MagicMock()
        mock_doc.__iter__.return_value = []
        mock_doc.__enter__ = MagicMock(return_value=mock_doc)
        mock_doc.__exit__ = MagicMock(return_value=False)
        mock_fitz.open.return_value = mock_doc

        with patch.dict(sys.modules, {"fitz": mock_fitz}):
            from app.features.ocr_service import _pdf_to_images
            with pytest.raises(ValueError, match="没有可渲染的页面"):
                _pdf_to_images(b"empty pdf")


# ============================================================
# _call_ocr_api
# ============================================================


# ============================================================
# OCRFixRouter adapter chaining tests (replaces old _call_ocr_api / ocr_fallback tests)
# ============================================================


@pytest.fixture
def mock_vl_adapter():
    """Fixture: mock PaddleOCRVLAdapter that always succeeds."""
    adapter = AsyncMock()
    result = MagicMock()
    result.fixed_text = "识别出的题目文字内容 A. 选项1 B. 选项2 C. 选项3 D. 选项4"
    result.confidence = 0.92
    result.model_used = "paddleocr-vl"
    result.risk_flags = []
    result.safety = None
    adapter.fix.return_value = result
    return adapter


@pytest.fixture
def mock_deepseek_adapter():
    """Fixture: mock DeepSeek adapter that always succeeds."""
    adapter = AsyncMock()
    result = MagicMock()
    result.fixed_text = "DeepSeek 修正的文字 A. 选项1 B. 选项2 C. 选项3 D. 选项4"
    result.confidence = 0.85
    result.model_used = "deepseek"
    result.risk_flags = []
    result.safety = None
    adapter.fix.return_value = result
    return adapter


@pytest.fixture
def mock_vl_unsafe_adapter():
    """Fixture: mock PaddleOCRVLAdapter returning collapsed text rejected by safety gate.

    The output is dramatically shorter than the input, which triggers the
    ``length_collapse`` check in ``safe_accept_ai_result``.
    Used to verify the router rejects unsafe candidates.
    """
    adapter = AsyncMock()
    result = MagicMock()
    result.fixed_text = "短"
    result.confidence = 0.95
    result.model_used = "paddleocr-vl"
    result.risk_flags = ["length_collapse"]
    result.safety = None
    adapter.fix.return_value = result
    return adapter


@pytest.fixture
def mock_empty_adapter():
    """Fixture: mock adapter returning empty result."""
    adapter = AsyncMock()
    result = MagicMock()
    result.fixed_text = ""
    result.confidence = 0.0
    result.model_used = "paddleocr-vl"
    adapter.fix.return_value = result
    return adapter


@pytest.fixture
def mock_failing_adapter():
    """Fixture: mock adapter that raises an exception."""
    adapter = AsyncMock()
    adapter.fix.side_effect = Exception("API connection failed")
    return adapter


class TestOCRFixRouter:
    """Test OCRFixRouter adapter chaining — replaces old _call_ocr_api / ocr_fallback tests.

    Adapters are injected directly via OCRFixRouter(adapters={...}) so the
    lazy _get_adapter path is bypassed and we can test chaining logic in isolation.
    """

    @pytest.mark.asyncio
    async def test_vl_success_routes_to_no_deepseek(self, mock_vl_adapter):
        """VL adapter succeeds → validator accepts → no further adapters called."""
        mock_deepseek = AsyncMock()
        from app.features.ocr_fix.router import OCRFixRouter

        router = OCRFixRouter(adapters={
            "paddleocr-vl": mock_vl_adapter,
            "deepseek": mock_deepseek,
        })
        router.configure({"ocr_fix_strategy": "auto"})
        result = await router.fix(
            image=b"fake-image",
            ocr_text="some text",
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
            "deepseek": mock_deepseek_adapter,
        })
        # Use auto strategy to enable full chain
        router.configure({"ocr_fix_strategy": "auto"})
        result = await router.fix(
            image=b"fake-image",
            ocr_text="some text",
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
            "deepseek": mock_deepseek_adapter,
        })
        router.configure({"ocr_fix_strategy": "auto"})
        result = await router.fix(
            image=b"fake-image",
            ocr_text="some text",
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
            "deepseek": mock_deepseek_adapter,
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
        mock_deepseek_unsafe = AsyncMock()
        ds_result = MagicMock()
        ds_result.fixed_text = "短"
        ds_result.confidence = 0.85
        ds_result.model_used = "deepseek"
        ds_result.risk_flags = ["length_collapse"]
        ds_result.safety = None
        mock_deepseek_unsafe.fix.return_value = ds_result

        mock_rule = AsyncMock()
        rule_result = MagicMock()
        rule_result.fixed_text = "Rule fallback text A. 选项1 B. 选项2"
        rule_result.confidence = 0.6
        rule_result.model_used = "rule_fallback"
        rule_result.risk_flags = []
        rule_result.safety = None
        mock_rule.fix.return_value = rule_result

        from app.features.ocr_fix.router import OCRFixRouter

        router = OCRFixRouter(adapters={
            "paddleocr-vl": mock_vl_unsafe_adapter,
            "deepseek": mock_deepseek_unsafe,
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
        mock_rule = AsyncMock()
        rule_result = MagicMock()
        rule_result.fixed_text = "Rule fallback text A. 选项1 B. 选项2 C. 选项3 D. 选项4"
        rule_result.confidence = 0.6
        rule_result.model_used = "rule_fallback"
        mock_rule.fix.return_value = rule_result

        from app.features.ocr_fix.router import OCRFixRouter

        router = OCRFixRouter(adapters={
            "paddleocr-vl": mock_failing_adapter,
            "deepseek": mock_failing_adapter,
            "rule_fallback": mock_rule,
        })
        router.configure({"ocr_fix_strategy": "auto"})
        result = await router.fix(
            image=b"fake-image",
            ocr_text="some text",
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
            "deepseek": mock_deepseek_adapter,
        })
        router.configure({"ocr_fix_strategy": "auto"})
        result = await router.fix(
            image=b"fake-image",
            ocr_text="some text",
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
        with patch.object(pipeline, "_run_extract", wraps=pipeline._run_extract) as wrapped, \
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
