"""OCR Adapter Lazy Loading — Verify adapters are loaded lazily, not at module level."""
from __future__ import annotations

import sys


def test_paddleocr_not_loaded_on_import():
    """Importing ocr_gateway should NOT trigger paddleocr import."""
    # Clear any pre-existing paddleocr import
    saved = {}
    for mod in list(sys.modules.keys()):
        if "paddleocr" in mod or "paddle" in mod:
            saved[mod] = sys.modules.pop(mod)

    # Import core modules
    from app.core import config  # noqa: F401
    from app.core.deployment_profile import DeploymentProfile  # noqa: F401
    from app.features.runtime_capabilities import (  # noqa: F401
        RuntimeCapabilities,
        build_runtime_capabilities,
    )

    # Verify paddleocr is NOT loaded
    paddle_loaded = [m for m in sys.modules if "paddleocr" in m or "paddle." in m]
    assert len(paddle_loaded) == 0, f"paddleocr/paddle modules loaded on import: {paddle_loaded}"

    # Restore the popped modules. Leaving them out of sys.modules makes the next
    # import create a NEW module object while code imported earlier (e.g.
    # app.features.ocr_vl.paddleocr_vl_client) still holds the old one — that
    # split breaks patch() identity in later tests.
    for mod, obj in saved.items():
        sys.modules[mod] = obj
