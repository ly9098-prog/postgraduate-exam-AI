"""OCR service gateway fallback regression tests.

The remote OCR worker client converts connection/timeout errors into
failed ``WorkerResult`` objects instead of raising. ``ocr_pages`` and
``ocr_pages_with_boxes`` must detect this and fall back to the local
CPU path when the environment is not restricted.
"""
from __future__ import annotations

import pytest

import app.services.ocr_service as ocr_service
from app.core.ocr_types import WorkerResult


class _FakeGateway:
    def __init__(self, results):
        self._results = results

    @property
    def is_gateway(self) -> bool:
        return True

    async def recognize_pages(self, images):
        return list(self._results)


def _failed_result(page_index: int) -> WorkerResult:
    return WorkerResult(
        page_index=page_index,
        status="failed",
        result=None,
        stable_error_code="REMOTE_UNREACHABLE",
    )


def _success_result(page_index: int, text: str) -> WorkerResult:
    return WorkerResult(
        page_index=page_index,
        status="success",
        result={"text": text},
    )


@pytest.fixture
def _fallback_env(monkeypatch):
    """Non-restricted environment with a mocked local CPU fallback."""
    monkeypatch.setattr(
        ocr_service, "is_restricted_ocr_environment", lambda: False,
    )
    monkeypatch.setattr(
        ocr_service, "_legacy_ocr_pages",
        lambda page_images: {idx: f"CPU:{idx}" for idx, _ in page_images},
    )


def test_ocr_pages_falls_back_when_all_results_failed(monkeypatch, _fallback_env):
    """Gateway returns only failed results (remote down) -> local CPU fallback."""
    monkeypatch.setattr(
        ocr_service, "get_gateway",
        lambda: _FakeGateway([_failed_result(0), _failed_result(1)]),
    )
    result = ocr_service.ocr_pages([(0, b"a"), (1, b"b")])
    assert result == {0: "CPU:0", 1: "CPU:1"}


def test_ocr_pages_returns_gateway_on_success(monkeypatch, _fallback_env):
    """Gateway returns successful results -> no fallback."""
    monkeypatch.setattr(
        ocr_service, "get_gateway",
        lambda: _FakeGateway([_success_result(0, "remote text")]),
    )
    result = ocr_service.ocr_pages([(0, b"a")])
    assert result == {0: "remote text"}


def test_ocr_pages_mixed_results_no_fallback(monkeypatch, _fallback_env):
    """Partial success (some pages failed, some ok) -> keep gateway results."""
    monkeypatch.setattr(
        ocr_service, "get_gateway",
        lambda: _FakeGateway([_success_result(0, "ok"), _failed_result(1)]),
    )
    result = ocr_service.ocr_pages([(0, b"a"), (1, b"b")])
    assert result == {0: "ok", 1: ""}


def test_ocr_pages_restricted_raises_no_fallback(monkeypatch):
    """Restricted environment must never fall back to local CPU."""
    monkeypatch.setattr(ocr_service, "is_restricted_ocr_environment", lambda: True)
    monkeypatch.setattr(
        ocr_service, "get_gateway",
        lambda: _FakeGateway([_failed_result(0)]),
    )
    with pytest.raises(RuntimeError):
        ocr_service.ocr_pages([(0, b"a")])


def test_ocr_pages_with_boxes_falls_back(monkeypatch, _fallback_env):
    """ocr_pages_with_boxes falls back when all results failed."""
    monkeypatch.setattr(
        ocr_service, "get_gateway",
        lambda: _FakeGateway([_failed_result(0)]),
    )
    monkeypatch.setattr(
        ocr_service, "_legacy_ocr_pages_with_boxes",
        lambda images, skip_rotation=False: {0: "CPU:0"},
    )
    result = ocr_service.ocr_pages_with_boxes([(0, b"a")])
    assert result == {0: "CPU:0"}
