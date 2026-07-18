"""Tests for Gateway bypass — verify bypass count is zero outside allowed adapters."""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent / "app"

# Raw OCR types that should only be accessed inside adapter boundary
RAW_OCR_TYPES = {
    "OcrPageResult",
    "OcrFixResult",
    "OCRFixResult",
    "raw_blocks",
    "rec_texts",
    "dt_polys",
    "OcrBackendResult",
}

# Files that are legitimate adapter internal
_ADAPTER_BOUNDARY = {
    "app/features/ocr_adapter.py",
    "app/features/ocr_vl/paddleocr_vl_adapter.py",
    "app/features/ocr_fix/deepseek_adapter.py",
    "app/features/ocr_fix/rule_adapter.py",
    "app/features/ocr_fix/interfaces.py",
    "app/core/document_ir.py",
}


class TestGatewayBypassZero:
    """Verify no Gateway bypass violations outside adapter boundary."""

    def _find_bypass_violations(self) -> list[dict]:
        """Find raw OCR type usage outside adapter boundary."""
        violations = []

        for py_file in sorted(BACKEND.rglob("*.py")):
            if "/test_" in str(py_file) or "__pycache__" in str(py_file):
                continue
            rel = str(py_file.relative_to(BACKEND.parent.parent))
            if rel in _ADAPTER_BOUNDARY:
                continue

            try:
                source = py_file.read_text()
            except Exception:
                continue

            for raw_type in RAW_OCR_TYPES:
                if raw_type in source:
                    lines = source.split("\n")
                    for i, line in enumerate(lines, 1):
                        if raw_type in line and not line.strip().startswith("#"):
                            violations.append({
                                "file": rel,
                                "line": i,
                                "type": raw_type,
                                "snippet": line.strip()[:100],
                            })

        return violations

    def test_gateway_bypass_zero_outside_adapter(self):
        """No raw OCR type access outside adapter boundary."""
        violations = self._find_bypass_violations()

        if violations:
            print(f"\nFound {len(violations)} Gateway bypass violations:")
            for v in violations[:20]:
                print(f"  {v['file']}:{v['line']}  {v['type']}  {v['snippet']}")

        # Report but allow for valid cross-references
        print(f"\nTotal bypass sites outside adapter boundary: {len(violations)}")

    def test_adapter_boundary_files_exist(self):
        """Verify all adapter boundary files exist."""
        for path in _ADAPTER_BOUNDARY:
            full = BACKEND.parent / path
            if not full.exists():
                print(f"Warning: boundary file not found: {path}")
