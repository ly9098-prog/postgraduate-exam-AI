"""统一上传入口 /pipeline/upload — 路由分流测试。"""
import asyncio
import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.features.pipeline_orchestrator import (
    _pipeline_store,
    get_pipeline_status,
    run_excel_pipeline_background,
)


class TestRunExcelPipelineBackground:
    def test_success_writes_store_with_source_type(self):
        mock_import = AsyncMock(return_value=("batch_abc", 5))
        asyncio.run(run_excel_pipeline_background(
            pipeline_id="xl_test_001",
            file_content=b"fake excel",
            source_file="test.xlsx",
            import_excel_fn=mock_import,
        ))

        status = asyncio.run(get_pipeline_status("xl_test_001"))
        assert status is not None
        assert status["status"] == "completed"
        assert status["source_type"] == "excel"
        assert status["batch_id"] == "batch_abc"
        assert status["stats"]["total"] == 5

    def test_failure_writes_store_with_source_type(self):
        mock_import = AsyncMock(side_effect=RuntimeError("parse error"))
        asyncio.run(run_excel_pipeline_background(
            pipeline_id="xl_fail_001",
            file_content=b"bad excel",
            source_file="bad.xlsx",
            import_excel_fn=mock_import,
        ))

        status = asyncio.run(get_pipeline_status("xl_fail_001"))
        assert status is not None
        assert status["status"] == "failed"
        assert status["source_type"] == "excel"
        assert "parse error" in status["errors"][0]


class TestPipelineUploadDispatch:
    """Test the pipeline_upload route handler dispatch logic."""

    @pytest.fixture
    def mock_deps(self):
        with patch("app.api.v1.imports.require_app_permission") as mock_perm, \
             patch("app.api.v1.imports.settings") as mock_settings:
            mock_perm.return_value = lambda: MagicMock()
            mock_settings.OCR_ENABLED = True
            mock_settings.IMAGE_IMPORT_MAX_BYTES = 10 * 1024 * 1024
            yield mock_settings

    def _make_upload_file(self, filename: str, content: bytes, content_type: str = "application/octet-stream"):
        mock_file = MagicMock()
        mock_file.filename = filename
        mock_file.content_type = content_type
        mock_file.read = AsyncMock(return_value=content)
        return mock_file

    def _make_background_tasks(self):
        bt = MagicMock()
        bt.add_task = MagicMock()
        return bt

    def test_unsupported_extension_returns_400(self):
        from app.api.v1.imports import pipeline_upload

        file = self._make_upload_file("doc.docx", b"content")
        bt = self._make_background_tasks()
        user = MagicMock()

        with pytest.raises(Exception) as exc_info:
            asyncio.run(pipeline_upload(file=file, background_tasks=bt, _=user))

        assert "400" in str(exc_info.value.status_code) or exc_info.value.status_code == 400

    def test_empty_file_returns_400(self):
        from app.api.v1.imports import pipeline_upload

        file = self._make_upload_file("test.pdf", b"")
        bt = self._make_background_tasks()
        user = MagicMock()

        with pytest.raises(Exception) as exc_info:
            asyncio.run(pipeline_upload(file=file, background_tasks=bt, _=user))

        assert exc_info.value.status_code == 400

    def test_empty_filename_returns_400(self):
        from app.api.v1.imports import pipeline_upload

        file = self._make_upload_file("", b"content")
        file.filename = ""
        bt = self._make_background_tasks()
        user = MagicMock()

        with pytest.raises(Exception) as exc_info:
            asyncio.run(pipeline_upload(file=file, background_tasks=bt, _=user))

        assert exc_info.value.status_code == 400

    def test_pdf_dispatch_returns_pl_prefix(self):
        from app.api.v1.imports import pipeline_upload

        file = self._make_upload_file("exam.pdf", b"%PDF-1.4 content")
        bt = self._make_background_tasks()
        user = MagicMock()

        result = asyncio.run(pipeline_upload(file=file, background_tasks=bt, _=user))

        assert result.pipeline_id.startswith("pl_")
        assert result.source_type == "pdf"
        assert result.status == "parsing"
        bt.add_task.assert_called_once()

    def test_txt_dispatch_returns_pl_prefix(self):
        from app.api.v1.imports import pipeline_upload

        file = self._make_upload_file("notes.txt", b"some text content")
        bt = self._make_background_tasks()
        user = MagicMock()

        result = asyncio.run(pipeline_upload(file=file, background_tasks=bt, _=user))

        assert result.pipeline_id.startswith("pl_")
        assert result.source_type == "txt"
        assert result.status == "parsing"

    def test_excel_dispatch_returns_xl_prefix(self):
        from app.api.v1.imports import pipeline_upload

        file = self._make_upload_file("questions.xlsx", b"PK\x03\x04 fake xlsx")
        bt = self._make_background_tasks()
        user = MagicMock()

        result = asyncio.run(pipeline_upload(file=file, background_tasks=bt, _=user))

        assert result.pipeline_id.startswith("xl_")
        assert result.source_type == "excel"
        assert result.status == "parsing"

    def test_image_dispatch_returns_img_prefix(self, mock_deps):
        from app.api.v1.imports import pipeline_upload

        png_header = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        file = self._make_upload_file("photo.png", png_header, content_type="image/png")
        bt = self._make_background_tasks()
        user = MagicMock()

        with patch("app.api.v1.imports._validate_image_content", return_value=(800, 600, "PNG")), \
             patch("app.api.v1.imports._set_image_pipeline_status", new_callable=AsyncMock) as mock_status, \
             patch("importlib.util.find_spec", return_value=MagicMock()):
            result = asyncio.run(pipeline_upload(file=file, background_tasks=bt, _=user))

        assert result.pipeline_id.startswith("img_")
        assert result.source_type == "image"
        assert result.status == "queued"
        mock_status.assert_called_once()
        bt.add_task.assert_called_once()

    def test_image_ocr_disabled_returns_400(self):
        from app.api.v1.imports import pipeline_upload

        png_header = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        file = self._make_upload_file("photo.png", png_header, content_type="image/png")
        bt = self._make_background_tasks()
        user = MagicMock()

        with patch("app.api.v1.imports.settings") as mock_settings:
            mock_settings.OCR_ENABLED = False
            mock_settings.IMAGE_IMPORT_MAX_BYTES = 10 * 1024 * 1024

            with pytest.raises(Exception) as exc_info:
                asyncio.run(pipeline_upload(file=file, background_tasks=bt, _=user))

            assert exc_info.value.status_code == 400
            assert "OCR" in str(exc_info.value.detail)


class TestPipelineStatusQuery:
    """Test that GET /pipelines/{id} finds status from both stores."""

    def test_orchestrator_store_found(self):
        _pipeline_store["pl_query_001"] = {
            "pipeline_id": "pl_query_001",
            "status": "completed",
            "source_type": "pdf",
        }
        status = asyncio.run(get_pipeline_status("pl_query_001"))
        assert status is not None
        assert status["source_type"] == "pdf"

    def test_orchestrator_store_not_found(self):
        status = asyncio.run(get_pipeline_status("pl_nonexistent_999"))
        assert status is None

    def test_excel_pipeline_in_orchestrator_store(self):
        _pipeline_store["xl_query_001"] = {
            "pipeline_id": "xl_query_001",
            "status": "completed",
            "source_type": "excel",
            "batch_id": "b123",
        }
        status = asyncio.run(get_pipeline_status("xl_query_001"))
        assert status is not None
        assert status["source_type"] == "excel"
        assert status["batch_id"] == "b123"
