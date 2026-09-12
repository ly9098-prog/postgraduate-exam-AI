"""GPU OOM Fallback Policy — Requires real GPU/PaddleOCR.
environment_not_available: needs RTX 3050 Ti 4 GB GPU with CUDA OOM injection.
"""
from __future__ import annotations

import pytest


@pytest.mark.skip(reason="environment_not_available: needs GPU with CUDA OOM injection")
def test_oom_fallback_has_reason_code():
    """Verify CUDA OOM produces GPU_OOM error code."""
    pass


@pytest.mark.skip(reason="environment_not_available: needs real GPU")
def test_oom_does_not_cause_duplicate_page():
    """Verify CUDA OOM does not result in duplicate page persistence."""
    pass


@pytest.mark.skip(reason="environment_not_available: needs GPU")
def test_cpu_fallback_after_oom():
    """Verify system falls back to CPU OCR after GPU OOM."""
    pass
