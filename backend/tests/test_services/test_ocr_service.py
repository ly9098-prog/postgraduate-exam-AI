"""Stage 9 OCR 增强服务 — 单元测试。AI 调用和 PyMuPDF 全部 mock。"""
import sys
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


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
        """缺少 paddleocr 时，带框接口也应直接抛出依赖错误。"""
        from app.services import ocr_service

        with patch.object(ocr_service.settings, "OCR_ENABLED", True), patch.object(
            ocr_service,
            "_ocr_instance",
            None,
        ), patch.dict(sys.modules, {"paddleocr": None}):
            with pytest.raises(RuntimeError, match="OCR 依赖未安装：paddleocr"):
                ocr_service.ocr_pages_with_boxes([(1, b"fake image")])


# ============================================================
# _prepare_ocr_image
# ============================================================


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
        assert prepared.size == (1000, 1500)

    def test_prepare_ocr_image_upscales_small_image_within_max_side(self):
        from PIL import Image
        from app.services.ocr_service import _OCR_MAX_SIDE, _prepare_ocr_image

        image = Image.new("RGB", (500, 800), "white")
        buf = BytesIO()
        image.save(buf, format="PNG")

        prepared = _prepare_ocr_image(buf.getvalue())

        assert prepared.mode == "RGB"
        assert prepared.size[0] == 1000
        assert max(prepared.size) <= _OCR_MAX_SIDE


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


class TestCallOcrApi:
    @staticmethod
    def _run_async(coro):
        """Run async coroutine in sync test."""
        import asyncio
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        # If there's a running loop, create a new one
        new_loop = asyncio.new_event_loop()
        try:
            return new_loop.run_until_complete(coro)
        finally:
            new_loop.close()

    def test_successful_ocr_call(self):
        """模拟 AI API 成功返回 OCR 文本。"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "识别出的题目文字内容"}}],
            "usage": {"total_tokens": 150},
        }

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        mock_deepseek = MagicMock()
        mock_deepseek.is_available.return_value = True
        mock_deepseek.client = mock_client
        mock_deepseek.api_key = "sk-test"
        mock_deepseek.base_url = "https://api.deepseek.com"

        with patch("app.ai.client.deepseek", mock_deepseek):
            from app.features.ocr_service import _call_ocr_api
            result = self._run_async(_call_ocr_api(b"fake-image-data", page_num=1))

        assert result is not None
        assert result["page"] == 1
        assert "识别出的题目文字内容" in result["text"]
        assert result["tokens_used"] == 150

    def test_api_unavailable(self):
        """DeepSeek API 不可用 → 返回 None。"""
        mock_deepseek = MagicMock()
        mock_deepseek.is_available.return_value = False

        with patch("app.ai.client.deepseek", mock_deepseek):
            from app.features.ocr_service import _call_ocr_api
            result = self._run_async(_call_ocr_api(b"fake-image", page_num=1))

        assert result is None

    def test_api_error_status(self):
        """API 返回非 200 → 返回 None。"""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad request"

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        mock_deepseek = MagicMock()
        mock_deepseek.is_available.return_value = True
        mock_deepseek.client = mock_client
        mock_deepseek.api_key = "sk-test"
        mock_deepseek.base_url = "https://api.deepseek.com"

        with patch("app.ai.client.deepseek", mock_deepseek):
            from app.features.ocr_service import _call_ocr_api
            result = self._run_async(_call_ocr_api(b"fake-image", page_num=1))

        assert result is None

    def test_api_exception(self):
        """API 调用抛异常 → 静默返回 None。"""
        mock_client = AsyncMock()
        mock_client.post.side_effect = Exception("Connection refused")

        mock_deepseek = MagicMock()
        mock_deepseek.is_available.return_value = True
        mock_deepseek.client = mock_client
        mock_deepseek.api_key = "sk-test"
        mock_deepseek.base_url = "https://api.deepseek.com"

        with patch("app.ai.client.deepseek", mock_deepseek):
            from app.features.ocr_service import _call_ocr_api
            result = self._run_async(_call_ocr_api(b"fake-image", page_num=1))

        assert result is None

    def test_api_timeout(self):
        """API 超时 → 静默返回 None。"""
        import httpx

        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.TimeoutException("timeout")

        mock_deepseek = MagicMock()
        mock_deepseek.is_available.return_value = True
        mock_deepseek.client = mock_client
        mock_deepseek.api_key = "sk-test"
        mock_deepseek.base_url = "https://api.deepseek.com"

        with patch("app.ai.client.deepseek", mock_deepseek):
            from app.features.ocr_service import _call_ocr_api
            result = self._run_async(_call_ocr_api(b"fake-image", page_num=3))

        assert result is None


# ============================================================
# ocr_fallback (main entry)
# ============================================================


class TestOcrFallback:
    def _setup_mocks(self, page_count=2, ocr_texts=None):
        """设置完整的 mock 链：fitz + deepseek + settings。"""
        if ocr_texts is None:
            ocr_texts = ["第一页识别的题目内容", "第二页识别的题目内容"]

        # mock fitz for _pdf_to_images
        mock_fitz = MagicMock()
        mock_doc = MagicMock()
        pages = []
        for _ in range(page_count):
            p = MagicMock()
            pix = MagicMock()
            pix.tobytes.return_value = b"png-data"
            p.get_pixmap.return_value = pix
            pages.append(p)
        mock_doc.__iter__.return_value = pages
        mock_doc.__enter__ = MagicMock(return_value=mock_doc)
        mock_doc.__exit__ = MagicMock(return_value=False)
        mock_fitz.open.return_value = mock_doc

        # mock deepseek for _call_ocr_api
        mock_client = AsyncMock()

        def _make_response(page_text):
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {
                "choices": [{"message": {"content": page_text}}],
                "usage": {"total_tokens": 100},
            }
            return resp

        mock_client.post = AsyncMock()
        call_count = [0]

        def _side_effect(*a, **kw):
            idx = min(call_count[0], len(ocr_texts) - 1)
            call_count[0] += 1
            return _make_response(ocr_texts[idx])

        mock_client.post.side_effect = _side_effect

        mock_deepseek = MagicMock()
        mock_deepseek.is_available.return_value = True
        mock_deepseek.client = mock_client
        mock_deepseek.api_key = "sk-test"
        mock_deepseek.base_url = "https://api.deepseek.com"

        return mock_fitz, mock_deepseek


    def test_successful_ocr_two_pages(self):
        """两页 PDF OCR 成功。"""
        mock_fitz, mock_deepseek = self._setup_mocks(
            page_count=2,
            ocr_texts=[
                "第一页：题目 1\n\n题目 1 的选项",
                "第二页：题目 2\n\n题目 2 的选项",
            ],
        )

        with patch.dict(sys.modules, {"fitz": mock_fitz}), \
             patch("app.ai.client.deepseek", mock_deepseek), \
             patch("app.features.ocr_service.settings") as mock_settings:
            mock_settings.OCR_ENABLED = True
            from app.features.ocr_service import ocr_fallback
            blocks = ocr_fallback(b"fake pdf")

        assert len(blocks) >= 2  # at least one block per page

    def test_blocks_format(self):
        """验证返回的 blocks 格式与 pipeline 兼容。"""
        mock_fitz, mock_deepseek = self._setup_mocks(
            page_count=1,
            ocr_texts=["题目文字内容"],
        )

        with patch.dict(sys.modules, {"fitz": mock_fitz}), \
             patch("app.ai.client.deepseek", mock_deepseek), \
             patch("app.features.ocr_service.settings") as mock_settings:
            mock_settings.OCR_ENABLED = True
            from app.features.ocr_service import ocr_fallback
            blocks = ocr_fallback(b"fake")

        assert isinstance(blocks, list)
        assert len(blocks) > 0
        for b in blocks:
            assert "page" in b
            assert "block_index" in b
            assert "text" in b
            assert isinstance(b["page"], int)
            assert isinstance(b["text"], str)
            assert len(b["text"]) > 0

    def test_ocr_disabled_raises(self):
        """OCR_ENABLED=False → 抛 RuntimeError。"""
        mock_fitz, mock_deepseek = self._setup_mocks(page_count=1, ocr_texts=["text"])

        with patch.dict(sys.modules, {"fitz": mock_fitz}), \
             patch("app.ai.client.deepseek", mock_deepseek), \
             patch("app.features.ocr_service.settings") as mock_settings:
            mock_settings.OCR_ENABLED = False
            from app.features.ocr_service import ocr_fallback
            with pytest.raises(RuntimeError, match="未启用"):
                ocr_fallback(b"fake")

    def test_paragraph_splitting(self):
        """双换行按段落切分 block。"""
        mock_fitz, mock_deepseek = self._setup_mocks(
            page_count=1,
            ocr_texts=["段落一\n\n段落二\n\n段落三"],
        )

        with patch.dict(sys.modules, {"fitz": mock_fitz}), \
             patch("app.ai.client.deepseek", mock_deepseek), \
             patch("app.features.ocr_service.settings") as mock_settings:
            mock_settings.OCR_ENABLED = True
            from app.features.ocr_service import ocr_fallback
            blocks = ocr_fallback(b"fake")

        assert len(blocks) == 3
        assert blocks[0]["text"] == "段落一"
        assert blocks[1]["text"] == "段落二"
        assert blocks[2]["text"] == "段落三"

    def test_all_pages_fail_raises(self):
        """所有页面 OCR 失败 → 抛 RuntimeError。"""
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

        # API returns error for all pages
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal error"
        mock_client.post.return_value = mock_response

        mock_deepseek = MagicMock()
        mock_deepseek.is_available.return_value = True
        mock_deepseek.client = mock_client
        mock_deepseek.api_key = "sk-test"
        mock_deepseek.base_url = "https://api.deepseek.com"

        with patch.dict(sys.modules, {"fitz": mock_fitz}), \
             patch("app.ai.client.deepseek", mock_deepseek), \
             patch("app.features.ocr_service.settings") as mock_settings:
            mock_settings.OCR_ENABLED = True
            from app.features.ocr_service import ocr_fallback
            with pytest.raises(RuntimeError, match="均失败"):
                ocr_fallback(b"fake")

    def test_partial_page_failure(self):
        """部分页面 OCR 失败，成功的页面正常返回。"""
        mock_fitz = MagicMock()
        mock_doc = MagicMock()
        pages = []
        for _ in range(2):
            p = MagicMock()
            pix = MagicMock()
            pix.tobytes.return_value = b"png"
            p.get_pixmap.return_value = pix
            pages.append(p)
        mock_doc.__iter__.return_value = pages
        mock_doc.__enter__ = MagicMock(return_value=mock_doc)
        mock_doc.__exit__ = MagicMock(return_value=False)
        mock_fitz.open.return_value = mock_doc

        mock_client = AsyncMock()

        _call_count = [0]

        async def _alternating_response(*a, **kw):
            cnt = _call_count[0]
            _call_count[0] += 1
            resp = MagicMock()
            if cnt == 0:  # First call succeeds
                resp.status_code = 200
                resp.json.return_value = {
                    "choices": [{"message": {"content": "成功识别的文字"}}],
                    "usage": {"total_tokens": 50},
                }
            else:  # Second call fails
                resp.status_code = 500
                resp.text = "Error"
            return resp

        mock_client.post = AsyncMock(side_effect=_alternating_response)

        mock_deepseek = MagicMock()
        mock_deepseek.is_available.return_value = True
        mock_deepseek.client = mock_client
        mock_deepseek.api_key = "sk-test"
        mock_deepseek.base_url = "https://api.deepseek.com"

        with patch.dict(sys.modules, {"fitz": mock_fitz}), \
             patch("app.ai.client.deepseek", mock_deepseek), \
             patch("app.features.ocr_service.settings") as mock_settings:
            mock_settings.OCR_ENABLED = True
            from app.features.ocr_service import ocr_fallback
            blocks = ocr_fallback(b"fake")

        # Should have blocks from the successful page
        assert len(blocks) > 0
        assert any("成功识别" in b["text"] for b in blocks)

    def test_empty_ocr_result_skipped(self):
        """OCR 返回空文本 → 该页跳过。"""
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

        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "   "}}],  # 仅空白
            "usage": {"total_tokens": 10},
        }
        mock_client.post.return_value = mock_response

        mock_deepseek = MagicMock()
        mock_deepseek.is_available.return_value = True
        mock_deepseek.client = mock_client
        mock_deepseek.api_key = "sk-test"
        mock_deepseek.base_url = "https://api.deepseek.com"

        with patch.dict(sys.modules, {"fitz": mock_fitz}), \
             patch("app.ai.client.deepseek", mock_deepseek), \
             patch("app.features.ocr_service.settings") as mock_settings:
            mock_settings.OCR_ENABLED = True
            from app.features.ocr_service import ocr_fallback
            with pytest.raises(RuntimeError, match="均失败"):
                ocr_fallback(b"fake")


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
        """PDF 文本 < 100 字符且 OCR 开启 → 触发 OCR fallback。"""
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
             patch(
                 "app.features.ocr_service.is_ocr_enabled",
                 return_value=True,
             ), \
             patch(
                 "app.features.ocr_service.ocr_fallback",
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
