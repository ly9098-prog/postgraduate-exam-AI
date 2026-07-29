"""Central cloud OCR isolation helpers.

This module never imports, probes, or initializes local OCR packages in a
restricted deployment. Profile parsing failures are treated as restricted.
"""
from __future__ import annotations

import importlib.util
import sys
from collections.abc import Mapping

from app.core.config import settings
from app.core.deployment_profile import DeploymentProfile, detect_deployment_profile

LOCAL_OCR_MODULE_ROOTS = ("paddle", "paddleocr")


def is_restricted_ocr_environment() -> bool:
    if (settings.APP_ENV or "").strip().lower() == "production":
        return True
    try:
        return detect_deployment_profile() == DeploymentProfile.CLOUD_API
    except Exception:
        return True


def loaded_local_ocr_modules(
    modules: Mapping[str, object] | None = None,
) -> list[str]:
    names = (modules or sys.modules).keys()
    return sorted(
        name
        for name in names
        if any(name == root or name.startswith(f"{root}.") for root in LOCAL_OCR_MODULE_ROOTS)
    )


def local_paddleocr_available() -> bool:
    """Probe PaddleOCR only when the resolved profile explicitly permits it."""
    if is_restricted_ocr_environment():
        return False
    return importlib.util.find_spec("paddleocr") is not None
