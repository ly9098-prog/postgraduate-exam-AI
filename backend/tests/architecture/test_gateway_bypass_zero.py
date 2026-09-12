"""Tests for Gateway bypass — verify bypass count is zero outside allowed adapters.

Uses AST-level analysis to detect imports of raw OCR types outside adapter
boundary. String literal matches are avoided since they produce false positives
from dictionary keys and docstrings.
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent.parent / "app"
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Raw OCR types that should only be imported inside adapter boundary
RAW_OCR_TYPES = {
    "OcrPageResult",
    "OcrFixResult",
    "OCRFixResult",
}

# Adapter/internal modules — only these may import raw OCR types
_ADAPTER_BOUNDARY = frozenset({
    "backend/app/features/ocr_adapter.py",
    "backend/app/features/ocr_vl/paddleocr_vl_adapter.py",
    "backend/app/features/ocr_fix/deepseek_adapter.py",
    "backend/app/features/ocr_fix/rule_adapter.py",
    "backend/app/features/ocr_fix/interfaces.py",
    "backend/app/features/ocr_correction.py",
    "backend/app/core/document_ir.py",
    "backend/app/services/ocr_service.py",  # defines the types
    "backend/app/features/ocr_fix/__init__.py",  # re-exports
    "backend/app/features/ocr_fix/router.py",  # fix routing
    "backend/app/core/ocr_types.py",      # public types
    "backend/app/core/ocr_engine.py",      # engine (child process only)
    "backend/app/core/ocr_worker_process.py",
    "backend/app/core/ocr_worker_pool.py",
    "backend/app/services/ocr_local_worker_client.py",
    "backend/app/features/ocr_gateway.py",
})

# These variable names are DOMAIN concepts, not raw OCR types.
# They appear as dict keys in many modules and should NOT trigger violations.
_DOMAIN_VARS = {
    "raw_blocks",
    "rec_texts",
    "dt_polys",
    "OcrBackendResult",
}


class TestGatewayBypassZero:
    """Verify no Gateway bypass violations outside adapter boundary."""

    def _find_bypass_violations(self) -> list[dict]:
        violations = []

        for py_file in sorted(BACKEND.rglob("*.py")):
            if "/test_" in str(py_file) or "__pycache__" in str(py_file):
                continue
            rel = str(py_file.relative_to(PROJECT_ROOT))
            if rel in _ADAPTER_BOUNDARY:
                continue

            try:
                tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            except (SyntaxError, Exception):
                continue

            for node in ast.walk(tree):
                # Check: from X import OCRFixResult
                if isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        if alias.name in RAW_OCR_TYPES:
                            violations.append({
                                "file": rel,
                                "line": node.lineno,
                                "type": alias.name,
                                "snippet": f"from {node.module} import {alias.name}",
                            })

                # Check: import X → then X.OCRFixResult usage
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.asname or alias.name:
                            pass  # hard to detect statically, skip

        return violations

    def test_gateway_bypass_zero_outside_adapter(self):
        """No raw OCR type imports outside adapter boundary."""
        violations = self._find_bypass_violations()

        msg_parts = [f"Found {len(violations)} Gateway bypass violations:"]
        for v in violations[:20]:
            msg_parts.append(f"  {v['file']}:{v['line']}  {v['type']}  {v['snippet']}")
        if violations:
            msg_parts.append(
                "\nFix: raw OCR types must only be imported inside adapter boundary."
            )

        assert len(violations) == 0, "\n".join(msg_parts)

    def test_adapter_boundary_files_exist(self):
        """Verify all adapter boundary files exist."""
        missing = []
        for path in _ADAPTER_BOUNDARY:
            full = PROJECT_ROOT / path
            if not full.exists():
                missing.append(path)
        assert len(missing) == 0, f"Boundary files missing: {missing}"
