"""DeviceResolver tests — CPU, GPU, AUTO modes and fail-fast rules."""
from __future__ import annotations

import pytest

from app.ocr_worker.device import (
    OCRDevice,
    DeviceResolutionError,
    _PADDLE_UNAVAILABLE,
    resolve_ocr_device,
)


class TestOCRDeviceResolver:
    """Verify device resolution rules."""

    def test_requested_cpu_returns_cpu(self):
        res = resolve_ocr_device(
            requested_device="cpu",
            _import_paddle=_make_mock_paddle(cuda=False),
        )
        assert res.resolved_device == "cpu"
        assert res.fallback_used is False
        assert res.compiled_with_cuda is False

    def test_requested_gpu_no_cuda_fails_when_required(self):
        with pytest.raises(DeviceResolutionError, match="GPU required"):
            resolve_ocr_device(
                requested_device="gpu",
                require_gpu=True,
                _import_paddle=_make_mock_paddle(cuda=False),
            )

    def test_requested_gpu_no_cuda_falls_back_when_not_required(self):
        res = resolve_ocr_device(
            requested_device="gpu",
            require_gpu=False,
            _import_paddle=_make_mock_paddle(cuda=False),
        )
        assert res.resolved_device == "cpu"
        assert res.fallback_used is True
        assert "GPU_BUILD_REQUIRED" in res.reason_codes

    def test_requested_gpu_device_count_zero_fails_when_required(self):
        with pytest.raises(DeviceResolutionError, match="GPU required"):
            resolve_ocr_device(
                requested_device="gpu",
                require_gpu=True,
                _import_paddle=_make_mock_paddle(cuda=True, devices=0),
            )

    def test_requested_gpu_device_count_zero_falls_back(self):
        res = resolve_ocr_device(
            requested_device="gpu",
            require_gpu=False,
            _import_paddle=_make_mock_paddle(cuda=True, devices=0),
        )
        assert res.resolved_device == "cpu"
        assert "GPU_DEVICE_NOT_FOUND" in res.reason_codes

    def test_requested_gpu_ok_returns_gpu(self):
        res = resolve_ocr_device(
            requested_device="gpu",
            require_gpu=True,
            gpu_device_id=0,
            _import_paddle=_make_mock_paddle(cuda=True, devices=2),
        )
        assert res.resolved_device == "gpu"
        assert res.device_id == 0
        assert res.fallback_used is False
        assert res.paddle_device_str == "gpu:0"

    def test_requested_gpu_with_device_id(self):
        res = resolve_ocr_device(
            requested_device="gpu",
            require_gpu=True,
            gpu_device_id=1,
            _import_paddle=_make_mock_paddle(cuda=True, devices=2),
        )
        assert res.resolved_device == "gpu"
        assert res.device_id == 1
        assert res.paddle_device_str == "gpu:1"

    def test_auto_with_cuda_returns_gpu(self):
        res = resolve_ocr_device(
            requested_device="auto",
            _import_paddle=_make_mock_paddle(cuda=True, devices=1),
        )
        assert res.resolved_device == "gpu"

    def test_auto_without_cuda_returns_cpu(self):
        res = resolve_ocr_device(
            requested_device="auto",
            _import_paddle=_make_mock_paddle(cuda=False),
        )
        assert res.resolved_device == "cpu"
        assert res.fallback_used is True

    def test_paddle_not_installed_fallback(self):
        res = resolve_ocr_device(
            requested_device="gpu",
            require_gpu=False,
            _import_paddle=_PADDLE_UNAVAILABLE,
        )
        assert res.resolved_device == "cpu"
        assert "PADDLE_NOT_INSTALLED" in res.reason_codes

    def test_paddle_not_installed_require_gpu_raises(self):
        with pytest.raises(DeviceResolutionError):
            resolve_ocr_device(
                requested_device="gpu",
                require_gpu=True,
                _import_paddle=_PADDLE_UNAVAILABLE,
            )


# ── Helpers ────────────────────────────────────────────────

def _make_mock_paddle(*, cuda: bool, devices: int = 0):
    """Create a mock paddle module for testing."""

    class _MockCuda:
        @staticmethod
        def device_count():
            return devices

    class _MockPaddle:
        __version__ = "3.3.0"
        cuda = _MockCuda

        @staticmethod
        def is_compiled_with_cuda():
            return cuda

        @staticmethod
        def set_device(dev):
            pass

    return _MockPaddle
