"""OCR Device Resolver — determine and verify GPU/CPU device for OCR execution."""
from __future__ import annotations

import enum
import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("postgraduate-ai.ocr-worker.device")

# Sentinel for testing — passes the "paddle not available" path
_PADDLE_UNAVAILABLE = object()


class OCRDevice(enum.StrEnum):
    CPU = "cpu"
    GPU = "gpu"
    AUTO = "auto"


class DeviceResolutionError(RuntimeError):
    """Raised when device resolution fails."""


@dataclass(frozen=True)
class OCRDeviceResolution:
    """Immutable result of OCR device resolution."""
    requested_device: str
    resolved_device: str
    device_id: int | None
    compiled_with_cuda: bool
    cuda_device_count: int
    paddle_device_str: str
    fallback_used: bool
    reason_codes: list[str] = field(default_factory=list)

    def require_gpu(self) -> None:
        """Raise if the resolved device is NOT GPU."""
        if self.resolved_device != OCRDevice.GPU.value:
            raise DeviceResolutionError(
                f"GPU required but resolved device is {self.resolved_device}. "
                f"Reasons: {self.reason_codes}"
            )


def resolve_ocr_device(
    requested_device: str = "",
    require_gpu: bool = False,
    gpu_device_id: int = 0,
    *,
    _import_paddle: Any = None,
) -> OCRDeviceResolution:
    """Resolve the OCR device based on configuration and runtime checks.

    Args:
        requested_device: One of "cpu", "gpu", "auto". If empty, reads
            ``OCR_WORKER_DEVICE`` env var (default "auto").
        require_gpu: If True and GPU not available, raises error.
            Reads ``OCR_WORKER_REQUIRE_GPU`` env var if not provided.
        gpu_device_id: Specific GPU device index. Reads
            ``OCR_WORKER_GPU_DEVICE_ID`` env var if 0.
        _import_paddle: For testing — pass a mock paddle module, or
            ``_PADDLE_UNAVAILABLE`` to simulate missing paddle.

    Returns:
        OCRDeviceResolution with the resolved device and evidence.

    Raises:
        DeviceResolutionError: If resolution fails.
    """
    # Read from env if not provided
    if not requested_device:
        requested_device = os.environ.get("OCR_WORKER_DEVICE", "auto")
    if not require_gpu:
        require_gpu = os.environ.get("OCR_WORKER_REQUIRE_GPU", "").lower() in ("true", "1")
    if gpu_device_id == 0:
        try:
            gpu_device_id = int(os.environ.get("OCR_WORKER_GPU_DEVICE_ID", "0"))
        except (ValueError, TypeError):
            gpu_device_id = 0

    reason_codes: list[str] = []

    # Get Paddle module
    if _import_paddle is _PADDLE_UNAVAILABLE:
        reason_codes.append("PADDLE_NOT_INSTALLED")
        if require_gpu and requested_device == OCRDevice.GPU.value:
            raise DeviceResolutionError(
                f"GPU required but Paddle is not installed "
                f"(require_gpu={require_gpu})"
            )
        return OCRDeviceResolution(
            requested_device=requested_device,
            resolved_device=OCRDevice.CPU.value,
            device_id=None,
            compiled_with_cuda=False,
            cuda_device_count=0,
            paddle_device_str="cpu",
            fallback_used=requested_device != OCRDevice.CPU.value,
            reason_codes=reason_codes,
        )
    if _import_paddle is not None:
        paddle = _import_paddle
    else:
        try:
            import paddle
        except ImportError:
            reason_codes.append("PADDLE_NOT_INSTALLED")
            if require_gpu and requested_device == OCRDevice.GPU.value:
                raise DeviceResolutionError(
                    f"GPU required but Paddle is not installed "
                    f"(require_gpu={require_gpu})"
                )
            return OCRDeviceResolution(
                requested_device=requested_device,
                resolved_device=OCRDevice.CPU.value,
                device_id=None,
                compiled_with_cuda=False,
                cuda_device_count=0,
                paddle_device_str="cpu",
                fallback_used=requested_device != OCRDevice.CPU.value,
                reason_codes=reason_codes,
            )

    # Check CUDA compilation
    compiled_with_cuda = paddle.is_compiled_with_cuda()
    cuda_device_count = int(paddle.cuda.device_count()) if compiled_with_cuda else 0

    # Resolve
    if requested_device == OCRDevice.GPU.value:
        if not compiled_with_cuda:
            reason_codes.append("GPU_BUILD_REQUIRED")
            if require_gpu:
                raise DeviceResolutionError(
                    f"GPU required but Paddle is not compiled with CUDA "
                    f"(require_gpu={require_gpu})"
                )
            return OCRDeviceResolution(
                requested_device=requested_device,
                resolved_device=OCRDevice.CPU.value,
                device_id=None,
                compiled_with_cuda=False,
                cuda_device_count=0,
                paddle_device_str="cpu",
                fallback_used=True,
                reason_codes=reason_codes,
            )

        if cuda_device_count == 0:
            reason_codes.append("GPU_DEVICE_NOT_FOUND")
            if require_gpu:
                raise DeviceResolutionError(
                    f"GPU required but cuda_device_count=0 "
                    f"(require_gpu={require_gpu})"
                )
            return OCRDeviceResolution(
                requested_device=requested_device,
                resolved_device=OCRDevice.CPU.value,
                device_id=None,
                compiled_with_cuda=True,
                cuda_device_count=0,
                paddle_device_str="cpu",
                fallback_used=True,
                reason_codes=reason_codes,
            )

        if gpu_device_id >= cuda_device_count:
            reason_codes.append("GPU_DEVICE_ID_INVALID")
            if require_gpu:
                raise DeviceResolutionError(
                    f"GPU device_id={gpu_device_id} >= device_count={cuda_device_count} "
                    f"(require_gpu={require_gpu})"
                )
            gpu_device_id = 0

        try:
            paddle_device = f"gpu:{gpu_device_id}"
            paddle.set_device(paddle_device)
        except Exception as e:
            reason_codes.append(f"GPU_INITIALIZATION_FAILED:{e}")
            if require_gpu:
                raise DeviceResolutionError(
                    f"GPU initialization failed: {e} (require_gpu={require_gpu})"
                ) from e
            return OCRDeviceResolution(
                requested_device=requested_device,
                resolved_device=OCRDevice.CPU.value,
                device_id=None,
                compiled_with_cuda=True,
                cuda_device_count=cuda_device_count,
                paddle_device_str="cpu",
                fallback_used=True,
                reason_codes=reason_codes,
            )
        return OCRDeviceResolution(
            requested_device=requested_device,
            resolved_device=OCRDevice.GPU.value,
            device_id=gpu_device_id,
            compiled_with_cuda=True,
            cuda_device_count=cuda_device_count,
            paddle_device_str=f"gpu:{gpu_device_id}",
            fallback_used=False,
            reason_codes=reason_codes,
        )

    elif requested_device == OCRDevice.CPU.value:
        try:
            paddle.set_device("cpu")
        except Exception:
            pass
        return OCRDeviceResolution(
            requested_device=requested_device,
            resolved_device=OCRDevice.CPU.value,
            device_id=None,
            compiled_with_cuda=compiled_with_cuda,
            cuda_device_count=cuda_device_count,
            paddle_device_str="cpu",
            fallback_used=False,
            reason_codes=reason_codes,
        )

    else:  # auto
        if compiled_with_cuda and cuda_device_count > 0:
            try:
                paddle_device = f"gpu:{min(gpu_device_id, cuda_device_count - 1)}"
                paddle.set_device(paddle_device)
                return OCRDeviceResolution(
                    requested_device=requested_device,
                    resolved_device=OCRDevice.GPU.value,
                    device_id=min(gpu_device_id, cuda_device_count - 1),
                    compiled_with_cuda=True,
                    cuda_device_count=cuda_device_count,
                    paddle_device_str=paddle_device,
                    fallback_used=False,
                    reason_codes=reason_codes,
                )
            except Exception:
                reason_codes.append("GPU_INIT_AUTO_FAILED")
        return OCRDeviceResolution(
            requested_device=requested_device,
            resolved_device=OCRDevice.CPU.value,
            device_id=None,
            compiled_with_cuda=compiled_with_cuda,
            cuda_device_count=cuda_device_count,
            paddle_device_str="cpu",
            fallback_used=True,
            reason_codes=reason_codes,
        )
