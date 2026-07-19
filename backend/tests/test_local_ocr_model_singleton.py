"""Local OCR Model Singleton — Requires real GPU/PaddleOCR environment.
environment_not_available: needs RTX 3050 Ti 4 GB with PaddleOCR installed.
"""
from __future__ import annotations

import pytest


@pytest.mark.skip(reason="environment_not_available: needs RTX 3050 Ti 4 GB GPU")
def test_model_initialized_once():
    """Verify PaddleOCR model is initialized only once per process."""
    pass


@pytest.mark.skip(reason="environment_not_available: needs real GPU")
def test_model_not_reinitialized_per_page():
    """Verify model instance is reused across pages, not recreated per page."""
    pass


@pytest.mark.skip(reason="environment_not_available: needs PaddleOCR")
def test_model_reuse_across_documents():
    """Verify model instance is reused across multiple documents."""
    pass
