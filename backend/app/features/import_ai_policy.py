"""Shared AI-call policies for import entry points.

Image imports already have a dedicated OCR pass.  Running the OCR-correction
router afterwards causes one model call per noisy OCR block and then a second
question-level repair pass.  The fast policy keeps semantic repair at the
question boundary so an ordinary single-question image needs at most one
AI-repair request after OCR.
"""

from __future__ import annotations

from typing import Any


def apply_image_single_pass_policy(
    options: dict[str, Any] | None,
    *,
    enabled: bool = True,
) -> dict[str, Any]:
    """Return import options with redundant image AI stages disabled.

    The policy deliberately does *not* disable the OCR provider itself.  It only
    prevents the extracted OCR text from being sent through additional
    block-level/model-specific repair stages before the canonical question-level
    ``repair`` stage.

    ``enabled=False`` preserves the caller's options unchanged and is useful as
    an escape hatch for diagnostics/comparison runs.
    """
    result: dict[str, Any] = dict(options or {})
    if not enabled:
        return result

    # Skip/remove the per-OCR-block correction stage.  Keep both switches for
    # compatibility with the stage definition and the runtime skip guard.
    result["enable_ocr_correction"] = False
    result["skip_ocr_correction"] = True

    # Code repair and Roman-numeral decision are folded into the general repair
    # prompt.  This avoids additional model calls for the same question.
    result["enable_code_structure_reconstruct"] = False
    result["enable_roman_repair_phase"] = False

    # Preserve the existing rule-first optimization for high-confidence items.
    result.setdefault("enable_low_risk_skip", True)
    result["_image_single_pass_ai"] = True
    return result
