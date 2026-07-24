"""Native Text Probe — Per-page text layer analysis with route recommendation.

Provides:
- NativeTextProbeResult: Per-page text layer metrics.
- NativeTextProbe: Analyzes PDF text layer quality and recommends routing strategy.

Shadow mode (NATIVE_TEXT_ROUTING_MODE=shadow): computes recommendation but
does NOT change the production route. Existing OCR path runs as usual.

Route recommendations:
  NATIVE_TEXT  — Clean text layer, use directly
  LOCAL_OCR    — Low-quality or no text layer, need OCR
  REMOTE_OCR_VL — Complex layout or high-quality OCR needed
  HYBRID       — Mixed content, partial text layer
  REVIEW       — Ambiguous, needs human review
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field

from app.features.input_gateway import InputDocument

logger = logging.getLogger(__name__)

# Mode env var
_NATIVE_TEXT_ROUTING_MODE = os.environ.get("NATIVE_TEXT_ROUTING_MODE", "off")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Minimum printable character ratio for a "clean" text layer
_PRINTABLE_RATIO_THRESHOLD = 0.85

# Maximum ratio of garbled/control characters
_GARBLED_RATIO_THRESHOLD = 0.10

# Minimum text bbox coverage of page area for "full text layer"
_TEXT_BBOX_COVERAGE_THRESHOLD = 0.05

# Maximum image coverage of page area before triggering LOCAL_OCR
_IMAGE_COVERAGE_THRESHOLD = 0.60

# Maximum ratio of duplicate glyphs (repeated single chars)
_DUPLICATE_GLYPH_RATIO_THRESHOLD = 0.30

# Minimum font count to consider text layer complete
_MIN_FONT_COUNT = 2

# Printable ASCII + CJK ranges
_PRINTABLE_RE = re.compile(
    r'[ -~ -ɏ一-鿿　-〿＀-￯'
    r' -⁯℀-⅏Ͱ-Ͽ'
    r'0-9a-zA-Z.,;:!?()（）【】《》""'' '
    r'+\-*/=<>≤≥≠∞∫∑∏√∪∩∈∅∀∃⇒⇔∧∨¬∂∇′″'
    r'πθαβγδεζηλμξστφχψω]'
)

# Control characters (except common whitespace)
_CONTROL_CHAR_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------


@dataclass
class NativeTextProbeResult:
    """Per-page native text layer analysis result."""
    page_index: int
    native_text: str = ""
    native_text_length: int = 0
    printable_ratio: float = 0.0
    garbled_ratio: float = 0.0
    text_bbox_coverage: float = 0.0
    image_coverage: float = 0.0
    duplicate_glyph_ratio: float = 0.0
    font_object_count: int = 0
    route_recommendation: str = "UNKNOWN"
    confidence: float = 0.0
    reason_codes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# NativeTextProbe
# ---------------------------------------------------------------------------


class NativeTextProbe:
    """Per-page text layer analyzer for PDF documents.

    Analyzes the native text layer quality and recommends the optimal
    processing route. Operates in shadow mode by default.

    Usage::

        probe = NativeTextProbe()
        result = probe.analyze_page(page_text, page_index=0)
    """

    def __init__(self, mode: str = "") -> None:
        self._mode = mode or _NATIVE_TEXT_ROUTING_MODE

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def is_shadow(self) -> bool:
        return self._mode == "shadow"

    def analyze_page(
        self,
        text: str,
        *,
        page_index: int = 0,
        page_width: float = 0,
        page_height: float = 0,
        text_bbox_area: float = 0,
        image_bbox_area: float = 0,
        font_count: int = 0,
    ) -> NativeTextProbeResult:
        """Analyze a single page's native text layer.

        Args:
            text: The native text extracted from the PDF page.
            page_index: Zero-based page index.
            page_width: Page width in points (for coverage calculation).
            page_height: Page height in points.
            text_bbox_area: Total area of text bounding boxes.
            image_bbox_area: Total area of image bounding boxes.
            font_count: Number of distinct fonts on the page.
        """
        reason_codes: list[str] = []
        text_len = len(text)

        if text_len == 0:
            return NativeTextProbeResult(
                page_index=page_index,
                native_text="",
                native_text_length=0,
                route_recommendation="LOCAL_OCR",
                confidence=0.0,
                reason_codes=["NO_NATIVE_TEXT"],
            )

        # Compute metrics
        printable_chars = _PRINTABLE_RE.findall(text)
        control_chars = _CONTROL_CHAR_RE.findall(text)

        printable_ratio = len(printable_chars) / text_len if text_len > 0 else 0
        garbled_ratio = len(control_chars) / text_len if text_len > 0 else 0

        # Text bbox coverage of page
        page_area = page_width * page_height
        text_coverage = (text_bbox_area / page_area) if page_area > 0 else 0
        image_coverage = (image_bbox_area / page_area) if page_area > 0 else 0

        # Duplicate glyph detection (single repeated characters)
        dup_glyph_ratio = self._detect_duplicate_glyphs(text)

        # Route recommendation
        route = self._recommend_route(
            printable_ratio=printable_ratio,
            garbled_ratio=garbled_ratio,
            text_coverage=text_coverage,
            image_coverage=image_coverage,
            dup_glyph_ratio=dup_glyph_ratio,
            font_count=font_count,
            reason_codes=reason_codes,
        )

        confidence = self._compute_confidence(
            printable_ratio, garbled_ratio, dup_glyph_ratio,
        )

        return NativeTextProbeResult(
            page_index=page_index,
            native_text=text[:500],  # store preview only
            native_text_length=text_len,
            printable_ratio=printable_ratio,
            garbled_ratio=garbled_ratio,
            text_bbox_coverage=text_coverage,
            image_coverage=image_coverage,
            duplicate_glyph_ratio=dup_glyph_ratio,
            font_object_count=font_count,
            route_recommendation=route,
            confidence=confidence,
            reason_codes=reason_codes,
        )

    # ── Private helpers ──

    def _detect_duplicate_glyphs(self, text: str) -> float:
        """Detect ratio of single repeated characters (potential garbage text).

        E.g. "AAAAAAAAAAAAAAAAA" or "12121212121212" patterns.
        """
        if len(text) < 10:
            return 0.0

        # Count consecutive runs of the same character
        dup_count = 0
        run_length = 1
        for i in range(1, len(text)):
            if text[i] == text[i - 1]:
                run_length += 1
            else:
                if run_length >= 5:
                    dup_count += run_length
                run_length = 1
        if run_length >= 5:
            dup_count += run_length

        return dup_count / len(text)

    def _recommend_route(
        self,
        *,
        printable_ratio: float,
        garbled_ratio: float,
        text_coverage: float,
        image_coverage: float,
        dup_glyph_ratio: float,
        font_count: int,
        reason_codes: list[str],
    ) -> str:
        """Determine the recommended route based on text layer quality."""
        # No meaningful text
        if printable_ratio < 0.3:
            reason_codes.append("LOW_PRINTABLE_RATIO")
            if image_coverage > _IMAGE_COVERAGE_THRESHOLD:
                reason_codes.append("HIGH_IMAGE_COVERAGE")
                return "REMOTE_OCR_VL"
            return "LOCAL_OCR"

        # Garbled text
        if garbled_ratio > _GARBLED_RATIO_THRESHOLD:
            reason_codes.append("HIGH_GARBLED_RATIO")
            return "LOCAL_OCR"

        # Duplicate glyphs (garbage text)
        if dup_glyph_ratio > _DUPLICATE_GLYPH_RATIO_THRESHOLD:
            reason_codes.append("HIGH_DUPLICATE_GLYPH")
            return "LOCAL_OCR"

        # Low font count suggests incomplete text layer
        if font_count < _MIN_FONT_COUNT and text_coverage < _TEXT_BBOX_COVERAGE_THRESHOLD:
            reason_codes.append("LOW_FONT_COUNT")
            return "LOCAL_OCR"

        # Mixed page with significant image content
        if image_coverage > _IMAGE_COVERAGE_THRESHOLD:
            reason_codes.append("SIGNIFICANT_IMAGE_CONTENT")
            if printable_ratio > _PRINTABLE_RATIO_THRESHOLD:
                return "HYBRID"
            return "REMOTE_OCR_VL"

        # Clean text with some coverage
        if printable_ratio >= _PRINTABLE_RATIO_THRESHOLD and text_coverage > 0:
            reason_codes.append("CLEAN_NATIVE_TEXT")
            return "NATIVE_TEXT"

        # Borderline: has text but insufficient quality
        reason_codes.append("BORDERLINE_TEXT_QUALITY")
        return "REVIEW"

    def _compute_confidence(
        self,
        printable_ratio: float,
        garbled_ratio: float,
        dup_glyph_ratio: float,
    ) -> float:
        """Compute overall confidence score [0, 1]."""
        score = 1.0
        if printable_ratio < _PRINTABLE_RATIO_THRESHOLD:
            score -= 0.3 * (1 - printable_ratio / _PRINTABLE_RATIO_THRESHOLD)
        score -= garbled_ratio * 2.0
        score -= dup_glyph_ratio
        return max(0.0, min(1.0, score))

    def analyze_document(
        self,
        document: InputDocument,
        page_texts: list[tuple[str, int]],
    ) -> list[NativeTextProbeResult]:
        """Analyze all pages of a document.

        Args:
            document: InputDocument to analyze.
            page_texts: List of (text, font_count) tuples, one per page.

        Returns:
            List of NativeTextProbeResult, one per page.
        """
        results: list[NativeTextProbeResult] = []
        for page_index, (text, font_count) in enumerate(page_texts):
            result = self.analyze_page(
                text,
                page_index=page_index,
                font_count=font_count,
            )
            results.append(result)

            if self.is_shadow:
                logger.debug(
                    "Shadow probe [p%d]: route=%s confidence=%.2f codes=%s",
                    page_index, result.route_recommendation,
                    result.confidence, result.reason_codes,
                )

        return results
