"""Gateway failure status dominates residual payload in mixed-page batches."""

from unittest.mock import MagicMock

import pytest

from app.core.ocr_types import WorkerResult
from app.services import ocr_service as service
from tests.test_services.ocr_failure_support import fake_gateway


def success(page=1, payload=None):
    return WorkerResult(
        page_index=page,
        status="success",
        result={"text": "good"} if payload is None else payload,
    )


@pytest.mark.parametrize("status", ["failed", "timeout", "cancelled"])
@pytest.mark.parametrize(
    "payload", [None, {"page_index": 99, "text": "untrusted residual", "failed": False}]
)
def test_worker_failure_dominates_residual_payload(status, payload):
    worker = WorkerResult(
        page_index=7, status=status, result=payload, stable_error_code="ENGINE_FAILURE"
    )
    result = service._worker_result_to_page_result(worker)
    assert result.page_index == 7
    assert result.failed is True
    assert result.error == "ENGINE_FAILURE"
    assert result.text == ""
    assert result.boxes == []


@pytest.mark.parametrize("payload", [None, {}, [], "bad payload"])
def test_success_status_with_unusable_payload_is_failed(payload):
    worker = WorkerResult(page_index=7, status="success", result=payload)
    result = service._worker_result_to_page_result(worker)
    assert result.page_index == 7
    assert result.failed is True
    assert result.error == "ocr.gateway_missing_result"


def test_worker_failure_without_code_has_stable_fallback():
    result = service._worker_result_to_page_result(
        WorkerResult(page_index=7, status="failed")
    )
    assert result.failed is True
    assert result.error == "ocr.gateway_execution_failed"


def test_valid_gateway_payload_preserves_references_and_blank_semantics():
    boxes = [{"bbox": [1, 2, 3, 4]}]
    transforms = [{"kind": "identity"}]
    payload = {"page_index": 7, "text": "", "boxes": boxes, "transforms": transforms}
    result = service._worker_result_to_page_result(success(7, payload))
    assert result.failed is False
    assert result.page_index == 7
    assert result.boxes is boxes
    assert result.transforms is transforms


@pytest.mark.parametrize("method", ["ocr_pages", "ocr_pages_with_boxes"])
@pytest.mark.parametrize(
    "payload", [{"text": "stale", "failed": False}, {"text": "stale", "failed": True}]
)
def test_mixed_gateway_failure_never_promotes_failed_text(monkeypatch, method, payload):
    failed = WorkerResult(
        page_index=7,
        status="failed",
        result=payload,
        stable_error_code="ENGINE_FAILURE",
    )
    fake_gateway(monkeypatch, [success(), failed])
    legacy = MagicMock(
        side_effect=AssertionError("mixed success must not rerun whole batch")
    )
    monkeypatch.setattr(service, "_legacy_" + method, legacy)
    result = getattr(service, method)([(1, b"a"), (7, b"b")])
    legacy.assert_not_called()
    if method == "ocr_pages":
        assert result == {1: "good", 7: ""}
    else:
        assert result[1].text == "good"
        assert result[7].failed is True
        assert result[7].text == ""


@pytest.mark.parametrize("method", ["ocr_pages", "ocr_pages_with_boxes"])
@pytest.mark.parametrize("payload", [{"text": "stale", "failed": True}, "bad payload"])
def test_all_unusable_payloads_trigger_existing_local_fallback(
    monkeypatch, method, payload
):
    fake_gateway(monkeypatch, [success(7, payload)])
    fallback = MagicMock(return_value={7: "synthetic fallback"})
    monkeypatch.setattr(service, "_legacy_" + method, fallback)
    assert getattr(service, method)([(7, b"synthetic")]) == {7: "synthetic fallback"}
    fallback.assert_called_once()


@pytest.mark.parametrize("method", ["ocr_pages", "ocr_pages_with_boxes"])
def test_reported_failure_payload_in_mixed_success_is_not_text_success(
    monkeypatch, method
):
    fake_gateway(
        monkeypatch,
        [success(), success(7, {"text": "stale", "failed": True, "error": "engine"})],
    )
    result = getattr(service, method)([(1, b"a"), (7, b"b")])
    if method == "ocr_pages":
        assert result[7] == ""
    else:
        assert result[7].failed is True


@pytest.mark.parametrize("method", ["ocr_pages", "ocr_pages_with_boxes"])
@pytest.mark.parametrize("payload", [{"text": "stale", "failed": True}, "bad payload"])
def test_unusable_gateway_result_cannot_fall_back_locally_in_cloud(
    monkeypatch, method, payload
):
    fake_gateway(monkeypatch, [success(7, payload)], restricted=True)
    fallback = MagicMock(side_effect=AssertionError("local fallback forbidden"))
    monkeypatch.setattr(service, "_legacy_" + method, fallback)
    with pytest.raises(RuntimeError, match="local OCR fallback is forbidden"):
        getattr(service, method)([(7, b"synthetic")])
    fallback.assert_not_called()


def test_none_converter_input_keeps_existing_failure():
    result = service._worker_result_to_page_result(None)
    assert result.failed is True
    assert result.error == "No result"


@pytest.mark.parametrize("method", ["ocr_pages", "ocr_pages_with_boxes"])
@pytest.mark.parametrize("payload", [None, {}, [], "bad payload"])
def test_missing_payload_in_mixed_success_keeps_other_pages(
    monkeypatch, method, payload
):
    worker = WorkerResult(page_index=7, status="success", result=payload)
    fake_gateway(monkeypatch, [success(), worker])
    fallback = MagicMock(side_effect=AssertionError("valid pages must be retained"))
    monkeypatch.setattr(service, "_legacy_" + method, fallback)
    result = getattr(service, method)([(1, b"a"), (7, b"b")])
    fallback.assert_not_called()
    if method == "ocr_pages":
        assert result == {1: "good", 7: ""}
    else:
        assert result[1].text == "good"
        assert result[7].failed is True
