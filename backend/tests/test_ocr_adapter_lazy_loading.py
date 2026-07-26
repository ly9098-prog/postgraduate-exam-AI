"""OCR Adapter Lazy Loading — Verify adapters are loaded lazily, not at module level."""
from __future__ import annotations

import sys


def test_paddleocr_not_loaded_on_import():
    """Importing ocr_gateway should NOT trigger paddleocr import."""
    # Clear any pre-existing paddleocr import
    for mod in list(sys.modules.keys()):
        if "paddleocr" in mod or "paddle" in mod:
            del sys.modules[mod]

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
