"""Resource ownership and rendered-page binding regression acceptance."""

import asyncio

import pytest

from app.core.ocr_types import OcrPageResult
from app.features import pipeline_orchestrator as target
from tests.test_services.scanned_pdf_support import make_scan


@pytest.fixture
def scan(monkeypatch):
    return make_scan(monkeypatch)


@pytest.mark.parametrize("boundary", ["length", "tags", "render", "engine", "reset"])
def test_acquired_document_always_closes_and_owned_progress_is_removed(scan, boundary):
    error = asyncio.CancelledError(boundary)
    if boundary == "length":
        scan.doc.__len__.side_effect = error
    elif boundary == "tags":
        scan.tags.side_effect = error
    elif boundary == "render":
        scan.doc.__getitem__.side_effect = error
    elif boundary == "engine":
        scan.boxes = error
    else:
        scan.reset.side_effect = error
    with pytest.raises(asyncio.CancelledError) as caught:
        scan.run(page_end=1)
    assert caught.value is error
    scan.doc.close.assert_called_once()
    assert scan.progress == {}
    scan.build.assert_not_called()


@pytest.mark.parametrize(
    "error", [ValueError("engine"), asyncio.CancelledError(), KeyboardInterrupt()]
)
def test_close_failure_keeps_original_failure_or_cancellation(scan, error):
    scan.boxes = error
    scan.doc.close.side_effect = RuntimeError("cleanup")
    with pytest.raises(type(error)) as caught:
        scan.run()
    assert caught.value is error
    assert scan.progress == {}
    assert any("cleanup" in note for note in error.__notes__)
    scan.build.assert_not_called()


def test_close_failure_on_success_is_still_fatal_and_clears_progress(scan):
    scan.doc.close.side_effect = RuntimeError("cleanup")
    with pytest.raises(RuntimeError, match="cleanup"):
        scan.run(page_end=1)
    assert scan.progress == {}
    scan.build.assert_not_called()


@pytest.mark.parametrize("boundary", ["length", "tags"])
def test_initialization_failure_does_not_clear_preexisting_unowned_progress(
    scan, boundary
):
    scan.progress["scan"] = "other attempt"
    mock = scan.doc.__len__ if boundary == "length" else scan.tags
    mock.side_effect = ValueError(boundary)
    with pytest.raises(ValueError, match=boundary):
        scan.run()
    scan.doc.close.assert_called_once()
    assert scan.progress == {"scan": "other attempt"}


@pytest.mark.parametrize("key", [42, 0, -1, "1", True, 1.0, None])
def test_invalid_result_keys_are_rejected_before_reset_or_projection(scan, key):
    scan.boxed.side_effect = None
    scan.boxed.return_value = {key: OcrPageResult(page_index=1, text="untrusted")}
    with pytest.raises(ValueError, match="OCR batch"):
        scan.run(page_end=1)
    scan.reset.assert_not_called()
    scan.build.assert_not_called()
    scan.doc.close.assert_called_once()
    assert scan.progress == {}


@pytest.mark.parametrize("payload_index", [42, "1", True, 1.0, None])
def test_result_identity_must_match_rendered_page(scan, payload_index):
    scan.boxed.side_effect = None
    scan.boxed.return_value = {
        1: OcrPageResult(page_index=payload_index, text="wrong identity")
    }
    with pytest.raises(ValueError, match="OCR batch"):
        scan.run(page_end=1)
    scan.reset.assert_not_called()
    assert scan.progress == {}


@pytest.mark.parametrize(
    "result", [{}, {1: OcrPageResult(page_index=1, text="partial")}, None, []]
)
def test_missing_or_nonmapping_batch_results_are_not_partial_success(scan, result):
    scan.boxed.side_effect = None
    scan.boxed.return_value = result
    with pytest.raises(ValueError, match="OCR batch"):
        scan.run(page_end=2)
    scan.reset.assert_not_called()
    scan.build.assert_not_called()
    scan.doc.close.assert_called_once()
    assert scan.progress == {}


def test_previous_batch_page_cannot_be_reused_as_current_result(scan):
    scan.boxed.side_effect = [
        {
            1: OcrPageResult(page_index=1, text="first"),
            2: OcrPageResult(page_index=2, text="second"),
        },
        {1: OcrPageResult(page_index=1, text="stale result")},
    ]
    with pytest.raises(ValueError, match="OCR batch"):
        scan.run(page_end=3)
    assert scan.reset.call_count == 1
    scan.build.assert_not_called()
    assert scan.progress == {}


def test_successful_typed_results_preserve_original_boxes(scan):
    boxes = [{"bbox": [0, 1, 2, 3]}]
    scan.boxed.side_effect = None
    scan.boxed.return_value = {
        3: OcrPageResult(page_index=3, text=" exact ", boxes=boxes)
    }
    blocks = scan.run(page_start=3, page_end=3)
    assert blocks[0]["page"] == 3
    assert blocks[0]["text"] == " exact "
    assert blocks[0]["boxes"] is boxes
    assert scan.progress == {}


def test_progress_cleanup_failure_cannot_replace_cancellation(scan, monkeypatch):
    class BrokenProgress(dict):
        def pop(self, *args):
            raise RuntimeError("progress cleanup")

    progress = BrokenProgress()
    monkeypatch.setattr(target, "_ocr_progress", progress)
    error = asyncio.CancelledError()
    scan.boxes = error
    with pytest.raises(asyncio.CancelledError) as caught:
        scan.run()
    assert caught.value is error
    scan.doc.close.assert_called_once()
    assert any("cleanup" in note for note in error.__notes__)


def test_blank_pipeline_id_does_not_touch_progress_on_failure(scan):
    scan.progress["other"] = "retained"
    scan.boxes = ValueError("engine")
    with pytest.raises(ValueError, match="engine"):
        target._ocr_scanned_pdf(b"synthetic", page_end=1)
    assert scan.progress == {"other": "retained"}
    scan.doc.close.assert_called_once()


def test_progress_cleanup_failure_does_not_replace_first_close_failure(
    scan, monkeypatch
):
    class BrokenProgress(dict):
        def pop(self, *args):
            raise ValueError("progress cleanup")

    monkeypatch.setattr(target, "_ocr_progress", BrokenProgress())
    error = RuntimeError("close failed")
    scan.doc.close.side_effect = error
    with pytest.raises(RuntimeError) as caught:
        scan.run(page_end=1)
    assert caught.value is error
    assert any("progress cleanup" in note for note in error.__notes__)
    scan.build.assert_not_called()


@pytest.mark.parametrize("cancel", [False, True])
def test_extract_attempt_never_accepts_invalid_ocr_or_swallows_cancellation(
    scan, cancel
):
    from types import SimpleNamespace

    from app.features.pipeline_extract_diagnostics import resolve_extract_port
    from app.features.pipeline_extract_pdf import ExtractedContent, attempt_pdf_ocr

    original_blocks = [{"page": 1, "text": "synthetic original extraction"}]
    content = ExtractedContent(original_blocks)
    error = asyncio.CancelledError()
    scan.boxed.side_effect = error if cancel else None
    scan.boxed.return_value = {42: OcrPageResult(page_index=42, text="wrong source")}

    def attempt():
        attempt_pdf_ocr(
            SimpleNamespace(pipeline_id="scan"),
            b"synthetic pdf",
            {"page_end": 1},
            scan.settings,
            content,
            ports=lambda name: resolve_extract_port(target.__dict__, name),
        )

    if cancel:
        with pytest.raises(asyncio.CancelledError) as caught:
            attempt()
        assert caught.value is error
    else:
        attempt()
    assert content.raw_blocks is original_blocks
    assert not content.ocr_ok
    scan.doc.close.assert_called_once()
    assert scan.progress == {}
