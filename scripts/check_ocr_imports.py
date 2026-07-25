#!/usr/bin/env python3
"""Architecture import gate — verify OCR module import boundaries.

Ensures that domain modules (pipeline_orchestrator, question_pipeline, etc.)
do NOT directly import from ``app.services.ocr_service`` — they must go
through ``app.services.ocr_executor_service`` instead.

Allowed direct imports of ``ocr_service``:
- ``ocr_service`` itself (obviously)
- ``ocr_executor_service`` (the gateway)
- ``ocr_process_pool`` (process isolation layer)
- ``ocr_cache_service`` (cache is internal to the OCR layer)
- Tests (any file matching ``test_*.py``)

Usage:
    python scripts/check_ocr_imports.py
    echo $?  # 0 = clean, 1 = violations found
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

# Modules that are ALLOWED to directly import from ocr_service
_ALLOWED_MODULES = frozenset({
    "ocr_service",
    "ocr_executor_service",
    "ocr_process_pool",
    "ocr_cache_service",
    "ocr_runtime_config",
    # exercise_region_detector has a deprecated inline-ocr path with its own
    # lint rule (@warn_call). Not a model for new code.
    "exercise_region_detector",
})

# Specific names that ARE allowed when imported from app.services.ocr_service
# These are text-processing or diagnostic functions, not OCR inference gateways.
_ALLOWED_NAMES = frozenset({
    "clean_ocr_text",
    "get_ocr_cache_stats",
    "ocr_is_available",
    "get_ocr_init_error",
    "OcrPageResult",
    "OcrCandidateResult",
    "reset_ocr_engine",
    "ocr_raw_text",
    # sync ocr_pages uses shared thread pool (S0-04), async migration pending
    "ocr_pages",
    "ocr_pages_with_boxes",
})


def _module_name_from_path(path: Path, root: Path) -> str:
    """Convert a file path to a dotted module name relative to the project root."""
    rel = path.relative_to(root)
    parts = list(rel.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1].removesuffix(".py")
    # Remove the 'backend/' prefix if present
    if parts[0] == "backend":
        parts = parts[1:]
    return ".".join(parts)


def check_file(path: Path, root: Path) -> list[str]:
    """Check a single Python file for disallowed imports."""
    violations: list[str] = []
    module_name = _module_name_from_path(path, root)

    # Skip allowed modules and tests
    if any(allowed in module_name for allowed in _ALLOWED_MODULES):
        return violations
    if "test_" in module_name or "tests" in module_name:
        return violations

    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        violations.append(f"{path}: SyntaxError — cannot parse")
        return violations

    for node in ast.walk(tree):
        # from app.services.ocr_service import ocr_pages
        if isinstance(node, ast.ImportFrom):
            if node.module == "app.services.ocr_service":
                names = [alias.name for alias in node.names]
                disallowed = [n for n in names if n not in _ALLOWED_NAMES]
                if disallowed:
                    violations.append(
                        f"{path}:{node.lineno}: "
                        f"disallowed import from 'app.services.ocr_service' -> "
                        f"{disallowed} in {module_name} "
                        f"(use ocr_executor_service instead)"
                    )
            elif node.module and node.module.startswith("app.services.ocr_service"):
                names = [alias.name for alias in node.names]
                violations.append(
                    f"{path}:{node.lineno}: "
                    f"disallowed import of '{node.module}.{names}' "
                    f"in {module_name} (use ocr_executor_service instead)"
                )

        # from app.services import ocr_service → then ocr_service.ocr_pages
        # This catches the case where ocr_service is imported as a module
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "app.services.ocr_service" or alias.name.startswith("app.services.ocr_service."):
                    violations.append(
                        f"{path}:{node.lineno}: "
                        f"disallowed import '{alias.name}' "
                        f"in {module_name} (use ocr_executor_service instead)"
                    )

    return violations


def main() -> int:
    project_root = Path(__file__).resolve().parent.parent
    backend_dir = project_root / "backend" / "app"

    if not backend_dir.is_dir():
        print(f"Error: backend/app not found at {backend_dir}", file=sys.stderr)
        return 1

    all_violations: list[str] = []

    for py_file in sorted(backend_dir.rglob("*.py")):
        # Skip __pycache__ and venv
        if "__pycache__" in py_file.parts:
            continue
        violations = check_file(py_file, project_root)
        all_violations.extend(violations)

    if all_violations:
        print(f"OCR import boundary violations ({len(all_violations)} found):")
        print()
        for v in all_violations:
            print(f"  {v}")
        print()
        print("Fix: use ocr_executor_service instead of direct ocr_service imports.")
        return 1

    print("OK: No OCR import boundary violations.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
