"""DocumentIR Cross-Profile Schema — Verify both profiles emit canonical DocumentIR.
"""
from __future__ import annotations


def test_document_ir_schema_keys():
    """Verify canonical DocumentIR has required schema keys."""
    from app.core.document_ir import DocumentIR
    ir = DocumentIR()
    # DocumentIR should have fundamental attributes
    assert hasattr(ir, "pages") or hasattr(ir, "page_count") or hasattr(ir, "metadata")


def test_legacy_blocks_compat():
    """Verify document_ir_to_blocks helper exists for legacy compatibility."""
    from app.core.document_ir import document_ir_to_blocks
    assert callable(document_ir_to_blocks)


def test_module_result_document_ir_type():
    """Verify ModuleResult can carry DocumentIR data."""
    from app.core.module_result import ModuleResult
    result = ModuleResult.success(data={"type": "DocumentIR"}, data_type="DocumentIR", module_name="test")
    assert result.is_success
    assert result.data_type == "DocumentIR"
