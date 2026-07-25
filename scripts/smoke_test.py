#!/usr/bin/env python3
"""Import smoke test — verify that all core modules can be loaded without errors.

This catches missing dependencies, import cycles, and syntax errors
that may not be visible during normal startup.

Usage:
    python scripts/smoke_test.py
    echo $?  # 0 = all OK, 1 = failures
"""

from __future__ import annotations

import importlib
import sys
import traceback


def _check_modules() -> list[str]:
    errors: list[str] = []

    # Core modules that MUST import cleanly
    core_modules = [
        "app.core.config",
        "app.core.log_context",
        "app.core.document_ir",
        "app.core.transform_tracker",
        "app.core.ocr_runtime_config",
        "app.core.ocr_profile",
        "app.core.ocr_process_pool",
    ]

    # Service modules (some may fail due to missing optional deps)
    service_modules = [
        "app.services.ocr_executor_service",
        "app.services.ocr_cache_service",
    ]

    # Feature modules
    feature_modules = [
        "app.features.ai_safety",
        "app.features.candidate_evaluator",
        "app.features.pipeline_artifacts",
        "app.features.ocr_fix.interfaces",
    ]

    all_modules = core_modules + service_modules + feature_modules

    for mod_name in all_modules:
        try:
            importlib.import_module(mod_name)
            print(f"  OK  {mod_name}")
        except ImportError as exc:
            msg = str(exc)
            # Missing optional dependencies are OK (paddleocr, etc.)
            if any(opt in msg for opt in (
                "paddleocr", "paddle", "No module named 'paddle'",
            )):
                print(f"  ~   {mod_name} (optional dep missing: {exc})")
            else:
                print(f"  FAIL {mod_name}: {exc}")
                errors.append(mod_name)
        except Exception:
            print(f"  FAIL {mod_name}: (unexpected)")
            traceback.print_exc()
            errors.append(mod_name)

    return errors


def main() -> int:
    print("Import smoke test")
    print("=" * 60)

    sys.path.insert(0, "backend")

    errors = _check_modules()

    print()
    if errors:
        print(f"FAILED: {len(errors)} module(s) failed to import")
        for m in errors:
            print(f"  - {m}")
        return 1

    print("All modules imported successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
