"""OCR mode resolution and dependency validation.

Centralises the logic for:
- Parsing and validating ocr_mode values.
- Checking the correct dependencies based on mode (local vs api).
- Providing clear error messages for each mode.

Usage:
    from app.features.ocr_mode import resolve_ocr_mode, validate_ocr_mode_dependencies

    mode = resolve_ocr_mode(requested_mode)  # raises 422 if invalid
    validate_ocr_mode_dependencies(mode)     # raises 400 if deps missing
"""

from __future__ import annotations

import importlib
import logging
from typing import Literal

from app.core.config import settings
from app.core.deployment_profile import DeploymentProfile, detect_deployment_profile

logger = logging.getLogger(__name__)

VALID_OCR_MODES: set[str] = {"local", "api"}


def resolve_ocr_mode(mode: str | None) -> Literal["local", "api"]:
    """Resolve and validate the ocr_mode string.

    Returns a Literal["local", "api"].
    Raises ValueError if the mode is not recognised.
    """
    resolved = (mode or "").strip().lower()
    if not resolved:
        # cloud_api defaults to "api"; local_import defaults to "local"
        if detect_deployment_profile() == DeploymentProfile.CLOUD_API:
            resolved = "api"
        else:
            resolved = "local"
    if resolved not in VALID_OCR_MODES:
        raise ValueError(
            f"Invalid OCR mode: {mode!r}. Must be one of: {', '.join(sorted(VALID_OCR_MODES))}"
        )
    return resolved  # type: ignore[return-value]


def validate_ocr_mode_dependencies(mode: str) -> None:
    """Check that runtime dependencies for the given OCR mode are satisfied.

    Args:
        mode: "local" or "api" (must already be resolved via resolve_ocr_mode).

    Raises:
        RuntimeError: with a clear message specific to the mode when a dependency
                     is missing. Does NOT return a value — raises on first failure.
    """
    if mode == "local":
        # ``local`` is retained as the public/API compatibility value for the
        # standard OCR pipeline, but execution is selected by
        # OCR_EXECUTION_BACKEND.  In particular, paddlex_http is a remote
        # httpx/GPU backend and must not require local PaddleOCR packages.
        from app.core.ocr_runtime_config import get_runtime_config

        cfg = get_runtime_config()
        if not settings.OCR_ENABLED or not cfg.enabled:
            raise RuntimeError(
                "标准 OCR 功能未启用：请设置 OCR_ENABLED=true，或使用 ocr_mode=api"
            )
        if cfg.execution_backend == "disabled":
            raise RuntimeError("标准 OCR 执行后端已禁用（OCR_EXECUTION_BACKEND=disabled）")
        if cfg.execution_backend == "paddlex_http":
            if not cfg.remote_url:
                raise RuntimeError(
                    "OCR_EXECUTION_BACKEND=paddlex_http 但未配置 OCR_REMOTE_URL"
                )
            return
        if cfg.execution_backend == "local_process":
            if detect_deployment_profile() == DeploymentProfile.CLOUD_API:
                raise RuntimeError("cloud_api 环境不允许使用本地 OCR process")
            if importlib.util.find_spec("paddleocr") is None:
                raise RuntimeError(
                    "本地 OCR 依赖未安装：paddleocr。"
                    "请安装 PaddleOCR，或将 OCR_EXECUTION_BACKEND 配置为 paddlex_http"
                )
            return
        raise RuntimeError(f"不支持的 OCR_EXECUTION_BACKEND: {cfg.execution_backend}")
    elif mode == "api":
        # API mode: requires a configured remote OCR model (PaddleOCR-VL).
        # Does NOT check for local PaddleOCR installation.
        # We do a lightweight check here — the actual model config is resolved
        # at runtime in _run_vl_ocr().
        _check_api_dependencies()
    else:
        # Should not happen if resolve_ocr_mode was called first
        raise ValueError(f"Unsupported OCR mode: {mode}")


def _check_api_dependencies() -> None:
    """Check that API-mode dependencies are available.

    Only checks what can be verified synchronously at endpoint level:
    - The remote OCR feature is logically enabled (no env gate yet — feature gate
      may be added later).
    """
    # At minimum, OCR_ENABLED is not strictly required for api mode since
    # the local OCR path is not used. But we log a warning if it's disabled.
    if not settings.OCR_ENABLED:
        logger.info(
            "ocr_mode=api: OCR_ENABLED is false, but api mode only needs remote "
            "PaddleOCR-VL — proceeding without local PaddleOCR."
        )

    # No synchronous check for remote config — it's resolved async at runtime.
    # The endpoint will get a clear error from _run_vl_ocr if config is missing.
