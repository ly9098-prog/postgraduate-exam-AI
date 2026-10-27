"""Actual sync wrappers feed scanned PDF fallback and failed-page diagnostics."""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.core.ocr_types import OcrPageResult, WorkerResult
from app.services import ocr_service as service
from tests.test_services.ocr_failure_support import fake_executor
from tests.test_services.scanned_pdf_support import make_scan


@pytest.fixture
def pipeline(monkeypatch):
    boxed, text = service.ocr_pages_with_boxes, service.ocr_pages
    scan = make_scan(monkeypatch)
    monkeypatch.setattr(service, "ocr_pages_with_boxes", boxed)
    monkeypatch.setattr(service, "ocr_pages", text)
    executor = fake_executor(monkeypatch)
    return SimpleNamespace(scan=scan, executor=executor)


def worker(page, text="", status="success", payload=None):
    return WorkerResult(
        page_index=page,
        status=status,
        result={"text": text} if payload is None and status == "success" else payload,
        stable_error_code="ENGINE_FAILURE" if status != "success" else None,
    )


def test_missing_legacy_page_reaches_text_fallback_without_rerunning_valid_page(
    pipeline,
):
    p = pipeline
    boxes = [{"bbox": [1, 2, 3, 4]}]
    p.executor.boxed.return_value = {
        1: OcrPageResult(page_index=1, text="good", boxes=boxes)
    }
    p.executor.text.return_value = {2: " recovered "}
    blocks = p.scan.run(page_end=2)
    assert [b["text"] for b in blocks] == ["good", " recovered "]
    assert blocks[0]["boxes"] is boxes
    assert blocks[1]["source"] == "ocr_text_fallback"
    assert blocks[1]["_ocr_boxes_failed"] is True
    assert "_ocr_runtime_failed_pages" not in blocks[0]
    p.executor.text.assert_called_once_with([(2, b"png2")])
    assert p.executor.boxed.call_count == 1
    assert p.scan.progress == {}
    p.scan.doc.close.assert_called_once()


def test_executor_failure_preserves_unrecovered_pages_in_diagnostics(pipeline):
    p = pipeline
    p.executor.boxed.side_effect = RuntimeError("synthetic boxed failure")
    p.executor.text.return_value = {1: "recovered"}
    blocks = p.scan.run(page_end=2)
    assert [b["page"] for b in blocks] == [1]
    assert blocks[0]["source"] == "ocr_text_fallback"
    assert blocks[0]["_ocr_runtime_failed_pages"] == [2]
    assert (
        blocks[0]["_ocr_runtime_failed_pages"]
        is blocks[0]["_ocr_text_fallback_unavailable_pages"]
    )
    p.executor.text.assert_called_once_with([(1, b"png1"), (2, b"png2")])
    assert p.scan.progress == {}


@pytest.mark.parametrize(
    "payload", [None, {"page_index": 99, "text": "stale", "failed": False}]
)
def test_gateway_failed_page_reaches_text_fallback_using_requested_identity(
    pipeline, monkeypatch, payload
):
    p = pipeline
    gateway = SimpleNamespace(
        is_gateway=True,
        recognize_pages=MagicMock(
            side_effect=[
                [worker(1, "good"), worker(2, status="failed", payload=payload)],
                [worker(2, "recovered")],
            ]
        ),
    )
    monkeypatch.setattr(service, "get_gateway", lambda: gateway)
    blocks = p.scan.run(page_end=2)
    assert [b["text"] for b in blocks] == ["good", "recovered"]
    assert blocks[1]["page"] == 2
    assert blocks[1]["source"] == "ocr_text_fallback"
    assert gateway.recognize_pages.call_args_list[1].args == ([(2, b"png2")],)
    p.executor.boxed.assert_not_called()
    p.executor.text.assert_not_called()
    assert p.scan.progress == {}


def test_gateway_mixed_text_fallback_cannot_accept_failed_residual_text(
    pipeline, monkeypatch
):
    p = pipeline
    p.scan.profile.max_workers = 3
    gateway = SimpleNamespace(
        is_gateway=True,
        recognize_pages=MagicMock(
            side_effect=[
                [
                    worker(1, "good"),
                    worker(2, status="failed"),
                    worker(3, status="failed"),
                ],
                [
                    worker(2, "recovered"),
                    worker(3, status="failed", payload={"text": "untrusted"}),
                ],
            ]
        ),
    )
    monkeypatch.setattr(service, "get_gateway", lambda: gateway)
    blocks = p.scan.run(page_end=3)
    assert [b["text"] for b in blocks] == ["good", "recovered"]
    assert blocks[0]["_ocr_runtime_failed_pages"] == [3]
    p.executor.boxed.assert_not_called()
    p.executor.text.assert_not_called()


def test_real_blank_page_does_not_trigger_text_retry(pipeline):
    p = pipeline
    p.executor.boxed.return_value = {1: {"text": "", "boxes": []}}
    assert p.scan.run(page_end=1) == []
    p.executor.text.assert_not_called()
    assert p.scan.progress == {}


def test_legacy_cancellation_reaches_caller_after_pipeline_cleanup(pipeline):
    error = asyncio.CancelledError()
    pipeline.executor.boxed.side_effect = error
    with pytest.raises(asyncio.CancelledError) as caught:
        pipeline.scan.run(page_end=1)
    assert caught.value is error
    pipeline.scan.doc.close.assert_called_once()
    assert pipeline.scan.progress == {}
