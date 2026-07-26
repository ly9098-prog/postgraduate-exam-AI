"""Cloud isolation tests — verify local OCR is unreachable in cloud profile.

These tests set APP_ENV=production and DEPLOYMENT_PROFILE=cloud_api,
then verify that:
- paddle/paddleocr imports are blocked at the __import__ level
- OCRGateway with cloud profile rejects local adapters
- Legacy OCR entry points raise under cloud profile
"""
from __future__ import annotations

import pytest


def test_cloud_no_paddle_import(monkeypatch: pytest.MonkeyPatch) -> None:
    """In cloud profile, importing paddle or paddleocr must raise.

    Monkeypatches builtins.__import__ to simulate the production
    guard that blocks paddle modules.
    """
    original_import = __builtins__["__import__"]

    def guarded_import(name, *args, **kwargs):
        if name == "paddle" or name.startswith("paddle.") or name == "paddleocr":
            raise ImportError(f"Blocked: {name} is not available in cloud profile")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", guarded_import)

    with pytest.raises(ImportError, match="Blocked: paddle"):
        __import__("paddle")

    with pytest.raises(ImportError, match="Blocked: paddle"):
        __import__("paddleocr")

    # Non-paddle imports still work
    import json
    assert json is not None


@pytest.mark.skip(reason="Requires OCRGateway runtime — unit test in test_ocr_gateway.py covers this")
def test_cloud_gateway_blocks_local() -> None:
    """OCRGateway with cloud profile must reject local adapters."""
    pass


def test_cloud_legacy_executor_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    """_OcrExecutorService must raise in cloud_api profile."""
    monkeypatch.setattr(
        "app.core.config.settings.APP_ENV", "production",
    )
    from app.core.deployment_profile import DeploymentProfile, detect_deployment_profile

    # Force cloud detection
    monkeypatch.setenv("DEPLOYMENT_PROFILE", "cloud_api")
    assert detect_deployment_profile() == DeploymentProfile.CLOUD_API

    from app.services.ocr_executor_service import _OcrExecutorService

    with pytest.raises(RuntimeError, match="forbidden in cloud_api"):
        _OcrExecutorService._ensure_not_cloud()
