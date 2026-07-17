"""Static boundary tests — ensure backend private fields are NOT referenced outside adapters.

These tests scan the codebase for patterns that directly access backend-specific
fields in business logic code, which violates the adapter abstraction boundary.
"""
from __future__ import annotations

import ast
import os
import re
from pathlib import Path

import pytest

# Root directory of backend application code
BACKEND_APP = Path(__file__).resolve().parent.parent / "app"

# Backend-private field patterns that must NOT appear outside adapter code
BACKEND_PRIVATE_FIELDS: list[re.Pattern] = [
    re.compile(r"\blayoutParsingResults\b"),
    re.compile(r"\brec_texts\b"),
    re.compile(r"\bdt_polys\b"),
    re.compile(r"\berrorMsg\b"),
    re.compile(r"\bPaddleOCRVLResult\b"),
]

# Directories that are exempt (adapter implementations)
EXEMPT_DIRS: tuple[str, ...] = (
    "features/ocr_vl",
    "features/ocr_adapter",
    "services",
)


def _is_exempt(filepath: str) -> bool:
    """Check if a file is in an exempt directory."""
    path = filepath.replace(str(BACKEND_APP), "").lstrip("/")
    for ed in EXEMPT_DIRS:
        if path.startswith(ed):
            return True
    return False


class TestBackendFieldBoundary:
    """Scan for backend-private field references outside adapter code.

    These fields indicate a leak of the adapter abstraction boundary:
    business logic should read DocumentIR, not raw OCR backend output.
    """

    @pytest.mark.parametrize("pattern", BACKEND_PRIVATE_FIELDS, ids=lambda p: p.pattern[:20])
    def test_no_backend_fields_outside_adapter(self, pattern: re.Pattern) -> None:
        """Check that no Python file references a backend-private field."""
        violations: list[str] = []

        for root, _dirs, files in os.walk(str(BACKEND_APP)):
            for fn in files:
                if not fn.endswith(".py"):
                    continue
                fpath = os.path.join(root, fn)
                if _is_exempt(fpath):
                    continue

                try:
                    with open(fpath, encoding="utf-8") as f:
                        content = f.read()
                except Exception:
                    continue

                for lineno, line in enumerate(content.split("\n"), 1):
                    if pattern.search(line):
                        # Skip comments/docstrings that merely describe the field
                        stripped = line.strip()
                        if stripped.startswith("#") or stripped.startswith('"""'):
                            continue
                        rel = os.path.relpath(fpath, BACKEND_APP)
                        violations.append(f"{rel}:{lineno}: {stripped[:100]}")

        if violations:
            msg = "\n".join(violations[:20])
            pytest.fail(
                f"Backend private field '{pattern.pattern}' found outside adapter code:\n{msg}"
            )

    def test_no_direct_paddleocr_vl_result_imports(self):
        """Check PaddleOCRVLResult is not imported outside ocr_vl/ocr_adapter."""
        for root, _dirs, files in os.walk(str(BACKEND_APP)):
            for fn in files:
                if not fn.endswith(".py"):
                    continue
                fpath = os.path.join(root, fn)
                if _is_exempt(fpath):
                    continue

                try:
                    with open(fpath, encoding="utf-8") as f:
                        tree = ast.parse(f.read())
                except (SyntaxError, Exception):
                    continue

                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom):
                        names = [alias.name for alias in node.names]
                        if "PaddleOCRVLResult" in names:
                            rel = os.path.relpath(fpath, BACKEND_APP)
                            pytest.fail(
                                f"PaddleOCRVLResult imported in {rel} (outside adapter code)"
                            )
