"""AI OCR Correction Layer — backward-compatibility re-exports.

The shared detection/filter functions live in ocr_correction_common.py.
The AI correction logic was migrated to ocr_fix/router.py (strategy pattern
with Qwen→DeepSeek→rule fallback chain).

This module remains for backward-compatible imports only.
"""

from app.features.ocr_correction_common import (  # noqa: F401
    TIER_HIGH_THRESHOLD,
    TIER_MEDIUM_THRESHOLD,
    _classify_quality_tier,
    _detect_noise,
    _detect_structure_abnormal,
    _filter_sensitive,
    _should_correct,
)

__all__ = [
    "TIER_HIGH_THRESHOLD",
    "TIER_MEDIUM_THRESHOLD",
    "_classify_quality_tier",
    "_detect_noise",
    "_detect_structure_abnormal",
    "_filter_sensitive",
    "_should_correct",
]
