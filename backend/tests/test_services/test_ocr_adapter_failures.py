"""Missing legacy boxed pages and executor errors must remain explicit failures."""

import asyncio
from unittest.mock import MagicMock

import pytest

from app.core.ocr_types import OcrPageResult
from app.services import ocr_service as service
from tests.test_services.ocr_failure_support import fake_executor


@pytest.fixture
def executor(monkeypatch):
    return fake_executor(monkeypatch)


@pytest.mark.parametrize("raw", [{}, {7: None}, {7: {}}])
def test_missing_page_is_failed_with_stable_error(executor, raw):
    executor.boxed.return_value = raw
    result = service._legacy_ocr_pages_with_boxes(
        [(7, b"synthetic")], skip_rotation=True
    )
    assert list(result) == [7]
    assert result[7].page_index == 7
    assert result[7].failed is True
    assert result[7].error == "ocr.legacy_missing_result"
    assert result[7].text == ""
    executor.boxed.assert_called_once_with([(7, b"synthetic")], skip_rotation=True)


@pytest.mark.parametrize("raw", [None, [], "invalid mapping"])
def test_unusable_batch_is_failed_for_every_requested_page(executor, raw):
    executor.boxed.return_value = raw
    result = service._legacy_ocr_pages_with_boxes([(2, b"a"), (9, b"b")])
    assert list(result) == [2, 9]
    assert all(
        r.failed is True and r.error == "ocr.legacy_execution_failed"
        for r in result.values()
    )
    assert [r.page_index for r in result.values()] == [2, 9]


def test_executor_exception_is_not_blank_success_or_exception_text(executor):
    executor.boxed.side_effect = RuntimeError("synthetic exception marker")
    result = service._legacy_ocr_pages_with_boxes([(2, b"a"), (9, b"b")])
    assert all(r.failed is True for r in result.values())
    assert all(r.error == "ocr.legacy_execution_failed" for r in result.values())
    assert all(r.text == "" and r.boxes == [] for r in result.values())


@pytest.mark.parametrize("error", [asyncio.CancelledError(), KeyboardInterrupt()])
def test_cancellation_and_base_exception_are_not_converted_to_page_failures(
    executor, error
):
    executor.boxed.side_effect = error
    with pytest.raises(type(error)) as caught:
        service._legacy_ocr_pages_with_boxes([(7, b"synthetic")])
    assert caught.value is error


def test_partial_batch_preserves_valid_page_and_marks_missing_page(executor):
    boxes = [{"bbox": [0, 1, 2, 3]}]
    valid = OcrPageResult(page_index=2, text=" exact ", boxes=boxes)
    executor.boxed.return_value = {2: valid}
    result = service._legacy_ocr_pages_with_boxes([(2, b"a"), (9, b"b")])
    assert result[2] is valid
    assert result[2].boxes is boxes
    assert result[9].failed is True
    assert result[9].error == "ocr.legacy_missing_result"


@pytest.mark.parametrize(
    "raw", [OcrPageResult(page_index=7, text=""), {"text": "", "boxes": []}]
)
def test_explicit_blank_result_stays_successful(executor, raw):
    executor.boxed.return_value = {7: raw}
    result = service._legacy_ocr_pages_with_boxes([(7, b"synthetic")])
    assert result[7].failed is False
    assert result[7].text == ""
    assert result[7].error is None


def test_reported_failure_and_payload_fields_preserved(executor):
    boxes = [{"bbox": [0, 1, 2, 3]}]
    executor.boxed.return_value = {
        7: {
            "page_index": 7,
            "text": "raw",
            "boxes": boxes,
            "failed": True,
            "error": "engine failure",
        }
    }
    result = service._legacy_ocr_pages_with_boxes([(7, b"synthetic")])
    assert result[7].failed is True
    assert result[7].error == "engine failure"
    assert result[7].boxes is boxes


def test_cloud_guard_stops_before_executor_call(executor, monkeypatch):
    monkeypatch.setattr(service, "is_restricted_ocr_environment", lambda: True)
    with pytest.raises(RuntimeError, match="cloud_api"):
        service._legacy_ocr_pages_with_boxes([(7, b"synthetic")])
    executor.boxed.assert_not_called()


def test_empty_public_request_does_not_initialize_executor(monkeypatch):
    gateway = MagicMock()
    monkeypatch.setattr(service, "get_gateway", gateway)
    assert service.ocr_pages_with_boxes([]) == {}
    gateway.assert_not_called()
