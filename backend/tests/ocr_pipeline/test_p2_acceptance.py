"""P2 验收测试 — coordinator pipeline 安全治理。

验证：
1. 无 dummy_ir
2. 无 ModuleResult.success 在 no-op coordinator 的 run 方法中
3. adapter 不 import pipeline_orchestrator 私有函数
"""

from __future__ import annotations

from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent.parent / "app"


def test_no_dummy_ir_anywhere():
    """coordinator_orchestrator.py must not contain dummy_ir."""
    target = BACKEND / "features" / "coordinator_orchestrator.py"
    source = target.read_text(encoding="utf-8")
    assert "dummy_ir" not in source, "dummy_ir still present in coordinator_orchestrator.py"


def test_coordinators_not_implemented():
    """No-op coordinators must return NOT_IMPLEMENTED, not success."""
    target = BACKEND / "features" / "coordinators.py"
    source = target.read_text(encoding="utf-8")
    assert source.count("NOT_IMPLEMENTED") >= 3, (
        "Expected at least 3 NOT_IMPLEMENTED in coordinators.py"
    )


def test_adapter_no_legacy_orchestrator():
    """ocr_adapter.py must not import from pipeline_orchestrator."""
    target = BACKEND / "features" / "ocr_adapter.py"
    source = target.read_text(encoding="utf-8")
    assert "from app.features.pipeline_orchestrator import" not in source, (
        "ocr_adapter.py still imports from pipeline_orchestrator"
    )
    assert "_ocr_scanned_pdf" not in source, (
        "ocr_adapter.py still references _ocr_scanned_pdf"
    )
    assert "_blocks_to_document_ir" not in source, (
        "ocr_adapter.py still references _blocks_to_document_ir"
    )


def test_adapter_uses_standalone_builder():
    """ocr_adapter.py must use document_ir_builder instead of pipeline_orchestrator."""
    target = BACKEND / "features" / "ocr_adapter.py"
    source = target.read_text(encoding="utf-8")
    assert "document_ir_builder" in source, (
        "ocr_adapter.py must import from document_ir_builder"
    )


def test_coordinator_ocr_calls_gateway():
    """OCRCoordinator.run() must call gateway.recognize_page()."""
    target = BACKEND / "features" / "coordinators.py"
    source = target.read_text(encoding="utf-8")
    assert "gateway.recognize_page" in source, (
        "OCRCoordinator must call gateway.recognize_page(), not return gateway_ready stub"
    )
    assert "gateway_ready" not in source, (
        "OCRCoordinator must not return gateway_ready stub"
    )
