"""统一上传入口 /pipeline/upload — 路由分流测试。"""
import asyncio
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.features.pipeline_orchestrator import (
    _pipeline_store,
    get_pipeline_status,
    run_excel_pipeline_background,
)


@pytest.fixture(autouse=True)
def _bypass_resource_guard():
    """Bypass the temp-disk resource guard and Redis task queue on dev machines."""
    with patch("app.core.resource_guard.ResourceGuard.can_accept_work",
               return_value=(True, "")), \
         patch("app.core.resource_guard.ResourceGuard.acquire_reservation",
               new_callable=AsyncMock, return_value="fake-reservation-token"), \
         patch("app.core.resource_guard.ResourceGuard.release_reservation",
               new_callable=AsyncMock), \
         patch("app.services.task_queue_worker.enqueue_import_pipeline",
               new_callable=AsyncMock, return_value=MagicMock(reason=None)), \
         patch("app.services.task_queue_worker.enqueue_excel_pipeline",
               new_callable=AsyncMock, return_value=MagicMock(reason=None)), \
         patch("app.services.task_queue_worker.enqueue_image_pipeline",
               new_callable=AsyncMock, return_value=MagicMock(reason=None)):
        yield


@pytest.fixture
def _bypass_pipeline_checkpoint(monkeypatch):
    from app.features import pipeline_checkpoint
    from app.services import import_pipeline_admission

    async def noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr(pipeline_checkpoint, "ensure_pipeline_record", noop)
    monkeypatch.setattr(pipeline_checkpoint, "update_pipeline_status", noop)
    monkeypatch.setattr(import_pipeline_admission, "ensure_pipeline_record", noop)
    return noop


def _mock_stream_to_temp(path: str | None = None, content: bytes = b"dummy content"):
    """Return a context manager that patches ``stream_to_temp``.

    The mock returns a TempFile-like object with the given *path*
    (defaults to a real temp file path) and a no-op ``detach``.
    """
    tmp_path = path or os.path.join(tempfile.mkdtemp(), "upload.bin")
    if not os.path.exists(tmp_path):
        with open(tmp_path, "wb") as f:
            f.write(content)
    mock = MagicMock()
    mock.path = tmp_path
    mock.size = len(content)
    mock.detach.return_value = tmp_path
    mock.close = MagicMock()
    return patch("app.api.v1.imports.stream_to_temp", AsyncMock(return_value=mock))


def _mock_stream_to_temp_empty():
    """Return a context manager patching ``stream_to_temp`` to return an empty file."""
    return _mock_stream_to_temp(content=b"")


class TestRunExcelPipelineBackground:
    def test_success_writes_store_with_source_type(self, _bypass_pipeline_checkpoint):
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

    def test_failure_writes_store_with_source_type(self, _bypass_pipeline_checkpoint):
        mock_import = AsyncMock(side_effect=RuntimeError("parse error"))
        with pytest.raises(RuntimeError, match="parse error"):
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

    @pytest.fixture(autouse=True)
    def _bypass_checkpoint_for_dispatch(self, _bypass_pipeline_checkpoint):
        return _bypass_pipeline_checkpoint

    @pytest.fixture
    def mock_deps(self, _bypass_pipeline_checkpoint):
        with patch("app.api.v1.imports.require_app_permission") as mock_perm, \
             patch("app.core.config.settings") as mock_settings:
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
        user = MagicMock()

        with _mock_stream_to_temp():
            with pytest.raises(Exception) as exc_info:
                asyncio.run(pipeline_upload(file=file, current_user=user))

        assert "400" in str(exc_info.value.status_code) or exc_info.value.status_code == 400

    def test_empty_file_returns_400(self):
        from app.api.v1.imports import pipeline_upload

        file = self._make_upload_file("test.pdf", b"")
        user = MagicMock()

        with _mock_stream_to_temp_empty():
            with pytest.raises(Exception) as exc_info:
                asyncio.run(pipeline_upload(file=file, current_user=user))

        assert exc_info.value.status_code == 400

    def test_empty_filename_returns_400(self):
        from app.api.v1.imports import pipeline_upload

        file = self._make_upload_file("", b"content")
        file.filename = ""
        user = MagicMock()

        with _mock_stream_to_temp():
            with pytest.raises(Exception) as exc_info:
                asyncio.run(pipeline_upload(file=file, current_user=user))

        assert exc_info.value.status_code == 400

    def test_pdf_dispatch_returns_pl_prefix(self):
        from app.api.v1.imports import pipeline_upload

        file = self._make_upload_file("exam.pdf", b"%PDF-1.4 content")
        user = MagicMock()

        with _mock_stream_to_temp():
            result = asyncio.run(pipeline_upload(file=file, current_user=user))

        assert result.pipeline_id.startswith("pl_")
        assert result.source_type == "pdf"
        assert result.status == "parsing"

    def test_txt_dispatch_returns_pl_prefix(self):
        from app.api.v1.imports import pipeline_upload

        file = self._make_upload_file("notes.txt", b"some text content")
        user = MagicMock()

        with _mock_stream_to_temp():
            result = asyncio.run(pipeline_upload(file=file, current_user=user))

        assert result.pipeline_id.startswith("pl_")
        assert result.source_type == "txt"
        assert result.status == "parsing"

    def test_excel_dispatch_returns_xl_prefix(self):
        from app.api.v1.imports import pipeline_upload

        file = self._make_upload_file("questions.xlsx", b"PK\x03\x04 fake xlsx")
        user = MagicMock()

        with _mock_stream_to_temp():
            result = asyncio.run(pipeline_upload(file=file, current_user=user))

        assert result.pipeline_id.startswith("xl_")
        assert result.source_type == "excel"
        assert result.status == "parsing"

    def test_image_dispatch_returns_img_prefix(self, mock_deps):
        from app.api.v1.imports import pipeline_upload

        png_header = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        file = self._make_upload_file("photo.png", png_header, content_type="image/png")
        user = MagicMock()
        from app.schemas.import_review import PipelineUploadResponse
        mock_response = PipelineUploadResponse(
            pipeline_id="img_test_001",
            source_type="image",
            status="queued",
            filename="photo.png",
        )

        with patch("app.api.v1.imports.svc_start_import_pipeline", new_callable=AsyncMock, return_value=mock_response), \
             _mock_stream_to_temp():
            result = asyncio.run(pipeline_upload(file=file, current_user=user))

        assert result.pipeline_id.startswith("img_")
        assert result.source_type == "image"
        assert result.status == "queued"


    def test_image_ocr_disabled_returns_400(self):
        from app.api.v1.imports import pipeline_upload

        png_header = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        file = self._make_upload_file("photo.png", png_header, content_type="image/png")
        user = MagicMock()

        with patch("app.api.v1.imports.svc_start_import_pipeline", side_effect=ValueError("OCR not enabled")), \
             _mock_stream_to_temp():

            with pytest.raises(Exception) as exc_info:
                asyncio.run(pipeline_upload(file=file, current_user=user))

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
