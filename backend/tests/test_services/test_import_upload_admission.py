"""Admission order and failures for the actual shared upload entry."""

import asyncio
import sys
from types import SimpleNamespace

import pytest

from app.core import deployment_profile
from app.services import (
    import_document_upload,
    import_excel_upload,
    import_image_upload,
    import_pipeline_service,
    import_upload_service,
    task_queue_worker,
)
from app.services.task_queue_service import EnqueueResult


@pytest.fixture
def admission(monkeypatch, tmp_path):
    trace = []
    control = {"failure": None}
    queued = []
    statuses = []

    def mark(name):
        trace.append(name)
        if control["failure"] == name:
            raise RuntimeError(name)
        if control["failure"] == "cancel" and name == "queue":
            raise asyncio.CancelledError

    async def acquire(*_args):
        mark("reserve")

    async def release(*_args):
        mark("release")

    async def stage(*_args, **_kwargs):
        mark("stage")
        return SimpleNamespace(object_id="synthetic-staging")

    async def status(*args, **kwargs):
        mark("status")
        statuses.append((args, kwargs))

    async def queue(**kwargs):
        mark("queue")
        queued.append(kwargs)
        return EnqueueResult(control["failure"] != "reject", "task", "queue_full")

    class Document:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def __len__(self):
            return 10

    validator = SimpleNamespace(
        validate_file=lambda *_args: mark("validate"),
        validate_pdf_pages=lambda _pages: mark("pages"),
    )
    monkeypatch.setattr(import_upload_service, "get_upload_validator", lambda: validator)
    monkeypatch.setattr(import_pipeline_service, "_acquire_pipeline_reservation", acquire)
    monkeypatch.setattr(import_pipeline_service, "_release_pipeline_reservation", release)
    monkeypatch.setattr(import_pipeline_service, "_set_image_pipeline_status", status)
    monkeypatch.setattr(import_pipeline_service, "_validate_image_path", lambda _path: (40, 50, "PNG"))
    monkeypatch.setattr(import_pipeline_service, "_sha256_of_file", lambda _path: "abcdef0123456789")
    monkeypatch.setattr(import_image_upload.settings, "OCR_ENABLED", True)
    monkeypatch.setattr(
        deployment_profile, "detect_deployment_profile",
        lambda: deployment_profile.DeploymentProfile.CLOUD_API,
    )
    monkeypatch.setitem(sys.modules, "fitz", SimpleNamespace(open=lambda _path: Document()))
    for module in (import_document_upload, import_excel_upload, import_image_upload):
        monkeypatch.setattr(module, "async_store_file", stage)
    for module in (import_document_upload, import_excel_upload):
        monkeypatch.setattr(module, "_set_pipeline_store", status)
    for name in ("enqueue_import_pipeline", "enqueue_excel_pipeline", "enqueue_image_pipeline"):
        monkeypatch.setattr(task_queue_worker, name, queue)
    path = tmp_path / "synthetic-upload"
    path.write_bytes(b"synthetic input")
    return SimpleNamespace(
        trace=trace, control=control, queued=queued, statuses=statuses, path=str(path),
    )


async def start(admission, extension, **kwargs):
    return await import_upload_service.start_import_pipeline(
        file_path=admission.path, filename=f"input.{extension}", content_type=None, **kwargs,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("extension,source", [
    ("txt", "txt"), ("pdf", "pdf"), ("xlsx", "excel"), ("png", "image"),
])
async def test_success_keeps_reservation_and_original_queue_payload(admission, extension, source):
    response = await start(
        admission, extension, subject="data_structure", subject_id=3,
        enable_ai_repair=False, confidence_threshold=0.7, created_by="synthetic-admin",
    )
    expected = ["validate"] + (["pages"] if extension == "pdf" else [])
    assert admission.trace == expected + ["reserve", "stage", "status", "queue"]
    assert response.source_type == source
    assert response.status == ("queued" if source == "image" else "parsing")
    payload = admission.queued[0]
    assert payload["pipeline_id"] == response.pipeline_id
    assert payload["staging_object_id"] == "synthetic-staging"
    assert payload["source_file"] == f"input.{extension}"
    if source != "excel":
        assert payload["subject_id"] == 3
        assert payload["options"]["enable_ai_repair"] is False
        assert payload["options"]["confidence_threshold"] == 0.7
    if source in ("pdf", "txt"):
        assert payload["created_by"] == "synthetic-admin"
    if source == "pdf":
        assert response.page_range.total_pages == 10
        assert payload["options"]["page_start"] == 1
        assert payload["options"]["page_end"] == 10


@pytest.mark.asyncio
@pytest.mark.parametrize("extension", ["txt", "pdf", "xlsx", "png"])
@pytest.mark.parametrize("failure", ["reserve", "stage", "status", "queue", "reject"])
async def test_admission_failures_release_only_after_reservation(admission, extension, failure):
    admission.control["failure"] = failure
    error = ValueError if failure == "reject" else RuntimeError
    with pytest.raises(error):
        await start(admission, extension)
    if failure == "reserve":
        assert admission.trace[-1] == "reserve"
        assert "stage" not in admission.trace
        assert "release" not in admission.trace
    else:
        assert admission.trace[-1] == "release"
        assert admission.trace.count("release") == 1
    if failure == "reject":
        assert admission.trace[-3:] == ["queue", "status", "release"]


@pytest.mark.asyncio
@pytest.mark.parametrize("extension", ["txt", "xlsx", "png"])
async def test_non_pdf_range_rejects_before_admission(admission, extension):
    with pytest.raises(ValueError, match="仅适用于 PDF"):
        await start(admission, extension, page_start=2)
    assert admission.trace == ["validate"]


@pytest.mark.asyncio
async def test_pdf_range_is_forwarded_to_response_status_and_queue(admission):
    response = await start(admission, "pdf", page_start=3, page_end=6)
    assert response.page_range.selected_page_count == 4
    assert admission.queued[0]["options"]["page_start"] == 3
    assert admission.queued[0]["options"]["page_end"] == 6
    assert admission.statuses[0][0][1]["page_range"] == response.page_range.model_dump()


@pytest.mark.asyncio
async def test_queue_cancellation_preserves_existing_release_semantics(admission):
    admission.control["failure"] = "cancel"
    with pytest.raises(asyncio.CancelledError):
        await start(admission, "txt")
    assert admission.trace[-1] == "queue"
    assert "release" not in admission.trace
