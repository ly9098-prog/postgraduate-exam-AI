"""Synthetic legacy executor and gateway ports without OCR engine imports."""

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

from app.services import ocr_service


def fake_executor(monkeypatch):
    boxed = MagicMock(return_value={})
    text = MagicMock(return_value={})
    module = ModuleType("app.services.ocr_executor_service")
    module.ocr_executor = SimpleNamespace(
        run_ocr_pages_with_boxes=boxed, run_ocr_pages=text
    )
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(ocr_service, "_run_async", lambda result: result)
    monkeypatch.setattr(ocr_service, "is_restricted_ocr_environment", lambda: False)
    monkeypatch.setattr(ocr_service, "get_gateway", lambda: None)
    return SimpleNamespace(boxed=boxed, text=text)


def fake_gateway(monkeypatch, results, restricted=False):
    gateway = SimpleNamespace(
        is_gateway=True, recognize_pages=MagicMock(return_value=results)
    )
    monkeypatch.setattr(ocr_service, "get_gateway", lambda: gateway)
    monkeypatch.setattr(ocr_service, "_run_async", lambda result: result)
    monkeypatch.setattr(
        ocr_service, "is_restricted_ocr_environment", lambda: restricted
    )
    return gateway
