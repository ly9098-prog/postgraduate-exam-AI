"""Error/resource timing and runtime-port contracts shared with the old entry."""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.features import pipeline_orchestrator as target
from tests.test_services.scanned_pdf_support import make_scan


@pytest.fixture
def scan(monkeypatch):
    return make_scan(monkeypatch)


@pytest.mark.parametrize(
    "boundary", ["open", "length", "tags", "render", "collect", "ir"]
)
def test_failure_resource_and_progress_boundary(scan, monkeypatch, boundary):
    error = ValueError(boundary)
    if boundary == "open":
        scan.open.side_effect = error
    elif boundary == "length":
        scan.doc.__len__.side_effect = error
    elif boundary == "tags":
        scan.tags.side_effect = error
    elif boundary == "render":
        scan.doc.__getitem__.side_effect = error
    elif boundary == "collect":
        import gc

        monkeypatch.setattr(gc, "collect", MagicMock(side_effect=error))
    else:
        scan.build.side_effect = error
    with pytest.raises(ValueError, match=boundary):
        scan.run(page_end=1)
    assert scan.doc.close.call_count == (boundary in {"render", "collect", "ir"})
    assert scan.progress == (
        {"scan": "0/1 pages"} if boundary in {"render", "collect"} else {}
    )


@pytest.mark.parametrize("error", [ValueError("text"), asyncio.CancelledError()])
def test_text_error_retry_and_base_exception_propagation(scan, error):
    scan.boxes = {1: SimpleNamespace(failed=True)}
    scan.text.side_effect = error
    if isinstance(error, Exception):
        assert scan.run(page_end=1) == []
        assert scan.text.call_count == 2
        assert scan.reset.call_count == 2
        assert scan.progress == {}
    else:
        with pytest.raises(asyncio.CancelledError):
            scan.run(page_end=1)
        assert scan.text.call_count == 1
        assert scan.progress == {"scan": "0/1 pages"}
    scan.doc.close.assert_called_once()


def test_progress_observation_and_close_before_ir(scan):
    def build(blocks, *, pipeline_id):
        assert scan.progress == {}
        assert scan.events[-1] == "close"
        return scan.ir

    scan.build.side_effect = build
    original = scan.boxed.side_effect

    def observe(images, **kwargs):
        assert scan.progress == {"scan": f"{images[0][0] - 1}/3 pages"}
        return original(images, **kwargs)

    scan.boxed.side_effect = observe
    blocks = scan.run(page_end=3)
    assert len(blocks) == 3
    assert scan.events.count("collect") == 2
    assert scan.build.call_args.args[0] is blocks


def test_returned_pages_are_sorted_within_each_batch(scan):
    scan.boxed.side_effect = None
    scan.boxed.return_value = {
        2: SimpleNamespace(failed=False, text="second", boxes=[]),
        1: SimpleNamespace(failed=False, text="first", boxes=[]),
    }
    assert [b["text"] for b in scan.run(page_end=2)] == ["first", "second"]


def test_engine_functions_captured_before_open_but_reset_imported_per_batch(
    scan, monkeypatch
):
    from app.services import ocr_service

    replacement = MagicMock()

    def opening(source):
        monkeypatch.setattr(ocr_service, "ocr_pages_with_boxes", replacement)
        monkeypatch.setattr(ocr_service, "ocr_pages", replacement)
        monkeypatch.setattr(ocr_service, "reset_ocr_engine", replacement)
        return scan.doc

    scan.open.side_effect = opening
    assert len(scan.run(page_end=1)) == 1
    scan.boxed.assert_called_once()
    replacement.assert_called_once_with()
    scan.reset.assert_not_called()


def test_runtime_global_progress_and_ir_ports_are_live(scan, monkeypatch):
    new_progress = {}
    original = scan.boxed.side_effect
    new_build = MagicMock(return_value=None)

    def change_ports(*args, **kwargs):
        monkeypatch.setattr(target, "_ocr_progress", new_progress)
        monkeypatch.setattr(target, "_blocks_to_document_ir", new_build)
        return original(*args, **kwargs)

    scan.boxed.side_effect = change_ports
    blocks = scan.run(page_end=1)
    assert scan.progress == {"scan": "0/1 pages"}
    assert new_progress == {}
    assert "_document_ir" not in blocks[0]
    new_build.assert_called_once()
    scan.build.assert_not_called()


def test_source_tag_uses_path_and_truncates(scan):
    target._ocr_scanned_pdf("x" * 250, pipeline_id="scan", page_end=1)
    assert ("ocr.source", "x" * 200) in [call.args for call in scan.tags.call_args_list]
    scan.open.assert_called_once_with("x" * 250)


def test_zero_page_pdf_still_closes_and_builds_empty_ir(scan):
    scan.pages = 0
    assert scan.run() == []
    scan.doc.close.assert_called_once()
    scan.build.assert_called_once_with([], pipeline_id="scan")
    scan.boxed.assert_not_called()


@pytest.mark.parametrize("size", [0, -1])
def test_nonpositive_batch_size_keeps_range_behavior(scan, size):
    scan.profile.max_workers = size
    if size == 0:
        with pytest.raises(ValueError, match="range"):
            scan.run()
        assert scan.progress == {"scan": "0/5 pages"}
    else:
        assert scan.run() == []
        assert scan.progress == {}
    scan.doc.close.assert_called_once()


def test_invalid_render_dpi_closes_before_any_engine_call(scan, monkeypatch):
    monkeypatch.setenv("OCR_RENDER_DPI", "invalid")
    with pytest.raises(ValueError):
        scan.run()
    scan.doc.close.assert_called_once()
    scan.boxed.assert_not_called()
    assert scan.progress == {"scan": "0/5 pages"}


def test_close_error_prevents_result_finalization(scan):
    scan.doc.close.side_effect = RuntimeError("close failed")
    with pytest.raises(RuntimeError, match="close failed"):
        scan.run(page_end=1)
    assert scan.progress == {"scan": "1/1 pages"}
    scan.build.assert_not_called()


def test_profile_and_limits_captured_before_open(scan):
    scan.settings.MAX_OCR_PAGES = 1

    def opening(source):
        scan.settings.MAX_OCR_PAGES = 5
        scan.profile.max_workers = 5
        return scan.doc

    scan.open.side_effect = opening
    assert len(scan.run()) == 1
    scan.boxed.assert_called_once_with([(1, b"png1")], skip_rotation=True)


def test_dpi_is_read_again_on_next_page(scan, monkeypatch):
    original = scan.doc.__getitem__.side_effect

    def get_page(index):
        if index == 1:
            monkeypatch.setenv("OCR_RENDER_DPI", "144")
        return original(index)

    scan.doc.__getitem__.side_effect = get_page
    scan.run(page_end=3)
    assert [e[2] for e in scan.events if isinstance(e, tuple) and e[0] == "render"] == [
        200,
        200,
        144,
    ]
