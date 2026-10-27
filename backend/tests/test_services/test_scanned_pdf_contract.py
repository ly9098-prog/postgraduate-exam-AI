"""Collected business contracts for the synchronous local scanned-PDF path."""

import asyncio

import pytest

from app.core.ocr_types import OcrPageResult
from tests.test_services.scanned_pdf_support import make_scan


@pytest.fixture
def scan(monkeypatch):
    return make_scan(monkeypatch)


@pytest.mark.parametrize(
    ("start", "end", "cap", "expected"),
    [
        (1, None, 0, [1, 2, 3, 4, 5]),
        (2, 4, 0, [2, 3, 4]),
        (2, 5, 2, [2, 3]),
        (0, 2, -1, [1, 2]),
        (8, None, 0, []),
        (1, 0, 0, [1, 2, 3, 4, 5]),
        (4, 2, 0, []),
    ],
)
def test_page_selection(scan, start, end, cap, expected):
    scan.settings.MAX_OCR_PAGES = cap
    blocks = scan.run(page_start=start, page_end=end)
    assert [b["page"] for b in blocks] == expected
    assert [b["block_index"] for b in blocks] == list(range(len(expected)))
    assert all(b["page_index"] == b["page"] for b in blocks)
    assert scan.reset.call_count == (len(expected) + 1) // 2
    assert scan.progress == {}
    scan.doc.close.assert_called_once()
    assert scan.build.call_args.kwargs == {"pipeline_id": "scan"}
    if expected:
        assert blocks[0]["_document_ir"] is scan.ir
        assert ("_warnings" in blocks[0]) == (cap > 0 and 5 - max(start, 1) + 1 > cap)


def test_box_reference_and_empty_page_filter(scan):
    boxes = [{"bbox": [1, 2, 3, 4]}]
    scan.boxes = {
        1: OcrPageResult(page_index=1, failed=False, text="  ", boxes=[]),
        2: OcrPageResult(page_index=2, failed=False, text=" exact ", boxes=boxes),
    }
    blocks = scan.run(page_end=2)
    assert len(blocks) == 1
    assert blocks[0]["text"] == " exact "
    assert blocks[0]["boxes"] is boxes
    assert blocks[0]["has_boxes"] is True
    assert blocks[0]["page_width"] == 801
    assert blocks[0]["source"] == "ocr_boxes"


@pytest.mark.parametrize("failure", ["none", "first", "both", "empty"])
def test_text_fallback_and_reset_retry(scan, failure):
    scan.boxes = {2: OcrPageResult(page_index=2, failed=True, text="ignored", boxes=[])}
    scan.fallback = {2: " fallback "} if failure != "empty" else {}
    if failure == "first":
        scan.reset.side_effect = [RuntimeError("reset"), None]
    elif failure == "both":
        scan.reset.side_effect = RuntimeError("reset")
    blocks = scan.run(page_end=2)
    assert scan.reset.call_count == (2 if failure in {"first", "both"} else 1)
    if failure in {"both", "empty"}:
        assert len(blocks) == 1
        assert blocks[0]["_ocr_runtime_failed_pages"] == [2]
        assert (
            blocks[0]["_ocr_runtime_failed_pages"]
            is blocks[0]["_ocr_text_fallback_unavailable_pages"]
        )
    else:
        assert blocks[1]["text"] == " fallback "
        assert blocks[1]["boxes"] == []
        assert blocks[1]["_ocr_boxes_failed"] is True
        assert blocks[1]["source"] == "ocr_text_fallback"
        scan.text.assert_called_once_with([(2, b"png2")])


@pytest.mark.parametrize("error", [RuntimeError("engine"), asyncio.CancelledError()])
def test_exception_closes_document_and_clears_progress(scan, error):
    scan.boxes = error
    with pytest.raises(type(error)):
        scan.run()
    scan.doc.close.assert_called_once()
    assert scan.progress == {}
    scan.build.assert_not_called()


def test_timeout_between_batches_takes_precedence_over_cap(scan):
    scan.settings.MAX_OCR_PAGES = 4
    scan.profile.timeout_seconds = 2
    original = scan.boxed.side_effect

    def slow(*args, **kwargs):
        result = original(*args, **kwargs)
        scan.clock = 2
        return result

    scan.boxed.side_effect = slow
    blocks = scan.run()
    assert [b["page"] for b in blocks] == [1, 2]
    assert blocks[0]["_warnings"] == ["ocr_timeout: processed 2 blocks in 2s limit"]
    assert scan.progress == {}
    assert ("ocr.timed_out", True) in [c.args for c in scan.tags.call_args_list]


def test_dynamic_dpi_and_original_batch_arguments(scan, monkeypatch):
    monkeypatch.setenv("OCR_RENDER_DPI", "144")
    scan.run(page_start=3, page_end=3)
    assert ("render", 3, 144) in scan.events
    scan.boxed.assert_called_once_with([(3, b"png3")], skip_rotation=True)
    scan.text.assert_not_called()


def test_cloud_guard_precedes_pdf_open(scan, monkeypatch):
    from app.core import deployment_profile

    monkeypatch.setattr(
        deployment_profile,
        "detect_deployment_profile",
        lambda: deployment_profile.DeploymentProfile.CLOUD_API,
    )
    with pytest.raises(RuntimeError, match="forbidden in cloud_api"):
        scan.run()
    scan.open.assert_not_called()
    scan.doc.close.assert_not_called()


def test_unexpected_result_page_is_rejected_before_fallback(scan):
    scan.boxed.side_effect = None
    scan.boxed.return_value = {
        42: OcrPageResult(page_index=2, failed=False, text="stray", boxes=[])
    }
    with pytest.raises(ValueError, match="OCR batch"):
        scan.run(page_end=1)
    scan.doc.close.assert_called_once()
    assert scan.progress == {}
