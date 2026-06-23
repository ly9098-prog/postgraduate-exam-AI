"""Structure Freeze Stage — detect and freeze option structures before splitting.

This stage runs after text normalization and before question splitting.
It detects option patterns in OCR blocks and produces frozen structures that
downstream stages read but never modify.

Design:
    - Single deterministic stage for option extraction
    - Pure regex-based detection (no AI, no heuristics)
    - Output is immutable — downstream stages (split, normalize, repair) only read
    - Each block is scanned; detected options are recorded in a registry
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# ── Option detection patterns ──────────────────────────────────────────────

# A. B. C. D. / A) B) / ①. ②. / (A) (B)
_OPTION_LINE_RE = re.compile(
    r"^\s*([A-Da-d]|[①②③④]|\(\s*[A-Da-d]\s*\))\s*[.、:：)）\s]"
)
# Inline: A.xxx B.xxx C.xxx D.xxx on same line
_INLINE_OPTION_RE = re.compile(
    r"([A-Da-d])\s*[.、:：)）]\s*"
    r"([^A-Da-d\n]+?)"
    r"(?=\s*[A-Da-d]\s*[.、:：)）]|\s*$)"
)
# Inline circled: ①.xxx ②.xxx ③.xxx ④.xxx on same line
_CIRCLED_INLINE_RE = re.compile(
    r"([①②③④])\s*[.、:：]\s*"
    r"([^①②③④\n]+?)"
    r"(?=\s*[①②③④]\s*[.、:：]|\s*$)"
)
# Inline paren: (A)xxx (B)xxx (C)xxx (D)xxx on same line
_PAREN_INLINE_RE = re.compile(
    r"\(\s*([A-Da-d])\s*\)\s*"
    r"([^(\n]+?)"
    r"(?=\s*\(\s*[A-Da-d]\s*\)|\s*$)"
)
# Circled digits
_CIRCLED_RE = re.compile(r"[①②③④]")
# Circled digit → ABCD mapping
_CIRCLED_MAP = {"①": "A", "②": "B", "③": "C", "④": "D"}


def _detect_option_line(line: str) -> tuple[str, str] | None:
    """Detect if a line starts with an option marker and extract (key, text)."""
    stripped = line.strip()
    if not stripped:
        return None
    m = _OPTION_LINE_RE.match(stripped)
    if m:
        raw_key = m.group(1)
        # Normalize key
        if raw_key in _CIRCLED_MAP:
            key = _CIRCLED_MAP[raw_key]
        else:
            key = raw_key.upper()
            key = re.sub(r"[()]", "", key).strip()
        text = _OPTION_LINE_RE.sub("", stripped).strip()
        if key in "ABCD" and text:
            return key, text
    return None


def _detect_inline_options(text: str) -> dict[str, str]:
    """Detect inline options like 'A.xxx B.xxx C.xxx D.xxx'."""
    options: dict[str, str] = {}

    # Priority 1: paren inline ((A) (B) (C) (D)) — must check before standard
    # inline since paren format also matches the broader inline regex.
    paren_matches = list(_PAREN_INLINE_RE.finditer(text))
    if len(paren_matches) >= 2:
        for m in paren_matches:
            key = m.group(1).upper()
            value = m.group(2).strip().rstrip("(").strip()
            if key in "ABCD" and value:
                options[key] = value
        return options

    # Priority 2: standard inline (A. B. C. D.)
    matches = list(_INLINE_OPTION_RE.finditer(text))
    if len(matches) >= 2:
        for m in matches:
            key = m.group(1).upper()
            value = m.group(2).strip()
            if key in "ABCD" and value:
                options[key] = value
        return options

    # Priority 3: circled inline (①. ②. ③. ④.)
    circled_matches = list(_CIRCLED_INLINE_RE.finditer(text))
    if len(circled_matches) >= 2:
        for m in circled_matches:
            raw_key = m.group(1)
            key = _CIRCLED_MAP.get(raw_key, raw_key)
            value = m.group(2).strip()
            if key in "ABCD" and value:
                options[key] = value
        return options

    return {}


# ── Freeze stage entry point ──────────────────────────────────────────────


def run_structure_freeze_stage(
    normalized_blocks: list[dict],
    **kwargs: Any,
) -> dict:
    """Scan normalized OCR blocks and freeze detected option structures.

    This is a pure, deterministic stage. It scans each block's text for
    option patterns and builds a ``frozen_option_registry`` — a mapping of
    ``(page, block_index)`` → detected options. Downstream stages use the
    registry instead of re-extracting options from text.

    Args:
        normalized_blocks: OCR blocks with ``normalized_text`` field.

    Returns:
        dict with:
            - ``frozen_option_registry`` (dict): ``{(page, block_idx): {A: text, ...}}``
            - ``frozen_structures`` (list[dict]): serialized per-block frozen structures
            - ``warnings`` (list[str])
    """
    if not normalized_blocks:
        logger.warning("[FREEZE] empty normalized_blocks")
        return {
            "frozen_option_registry": {},
            "frozen_structures": [],
            "warnings": ["empty_blocks"],
        }

    registry: dict[str, dict[str, str]] = {}
    structures: list[dict] = []
    warnings: list[str] = []
    total_option_blocks = 0

    for block in normalized_blocks:
        text = block.get("normalized_text") or block.get("text", "")
        if not text:
            continue

        page = block.get("page", 1)
        block_idx = block.get("block_index", 0)
        registry_key = f"{page}:{block_idx}"

        options: dict[str, str] = {}
        option_lines_found: list[int] = []
        style: str = "abcd"

        lines = text.split("\n")
        for li, line in enumerate(lines):
            # First check for inline options (e.g. A.甲 B.乙 C.丙 D.丁 on one line)
            inline_opts = _detect_inline_options(line)
            if inline_opts:
                for k, v in inline_opts.items():
                    if k not in options:
                        options[k] = v
                        option_lines_found.append(li)
                # Inline options found: skip single-line detection for this line
                # (inline is more precise)
            else:
                # Try single-line option detection
                result = _detect_option_line(line)
                if result:
                    key, opt_text = result
                    if key not in options:
                        options[key] = opt_text
                        option_lines_found.append(li)

            # Detect circled style
            if _CIRCLED_RE.search(line.strip()[:5]):
                style = "circled"

        if options:
            total_option_blocks += 1
            registry[registry_key] = dict(options)
            structures.append({
                "page": page,
                "block_index": block_idx,
                "options": dict(options),
                "option_style": style,
                "option_lines": option_lines_found,
                "option_keys": sorted(options.keys()),
                "confidence": _compute_confidence(options),
                "is_frozen": True,
                "is_complete": options.keys() >= {"A", "B", "C", "D"},
            })
            logger.debug(
                "[FREEZE] block %s:%s options=%s style=%s",
                page, block_idx, sorted(options.keys()), style,
            )

    if total_option_blocks == 0:
        warnings.append("no_options_detected")

    logger.info(
        "[FREEZE] stage complete: %d/%d blocks with options, %d structures frozen",
        total_option_blocks, len(normalized_blocks), len(structures),
    )
    return {
        "frozen_option_registry": registry,
        "frozen_structures": structures,
        "warnings": warnings,
    }


def _compute_confidence(options: dict[str, str]) -> float:
    """Compute freeze confidence based on option completeness."""
    present = set(options.keys())
    required = {"A", "B", "C", "D"}
    missing = required - present

    if not missing:
        return 1.0
    if len(missing) <= 1:
        return 0.7
    if len(missing) <= 2:
        return 0.5
    return 0.3
