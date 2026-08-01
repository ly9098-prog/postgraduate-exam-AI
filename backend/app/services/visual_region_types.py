"""Canonical data types for visual region detection, cropping, and segment construction.

These types are shared across the OCR pipeline, review, and publish flows.
They define the contracts that all visual-region-related code must follow.

Coordinate spaces supported:
  - pdf_points: PDF point coordinates at 72 DPI (native PDF space)
  - image_pixels: pixel coordinates in the rendered page image
  - normalized_1000: 0-1000 normalized coordinates (PaddleOCR-VL default)
  - normalized_1: 0.0-1.0 normalized coordinates
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import StrEnum

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class CoordinateSpace(StrEnum):
    PDF_POINTS = "pdf_points"
    IMAGE_PIXELS = "image_pixels"
    NORMALIZED_1000 = "normalized_1000"
    NORMALIZED_1 = "normalized_1"


class VisualRegionType(StrEnum):
    DIAGRAM = "diagram"
    CHART = "chart"
    TABLE = "table"
    FORMULA = "formula"
    CODE = "code"
    OPTION_IMAGE = "option_image"
    ILLUSTRATION = "illustration"
    UNKNOWN = "unknown"


class SegmentType(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    MATH_IMAGE = "math_image"
    TABLE_IMAGE = "table_image"
    CODE_IMAGE = "code_image"
    NEWLINE = "newline"


class AssignmentMethod(StrEnum):
    """How a visual region is assigned to a question/option."""
    BETWEEN_QUESTIONS = "between_questions"
    BBOX_OVERLAP = "bbox_overlap"
    OPTION_REGION = "option_region"
    PAGE_CROSS = "page_cross"
    UNCERTAIN = "uncertain"
    UNASSIGNED = "unassigned"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class VisualRegion:
    """A visual region detected on a page, before assignment to a question.

    This is the page-level detection result, not attached to any question yet.
    Assignment happens in a later pipeline stage (visual_region_assign).
    """
    region_id: str
    region_type: VisualRegionType
    source_page: int
    bbox: tuple[float, float, float, float] | None  # (x0, y0, x1, y1)
    coordinate_space: CoordinateSpace
    confidence: float = 0.0
    alt: str | None = None
    raw_data: dict | None = None  # original block data from detector

    # Populated after cropping
    image_url: str | None = None
    crop_failed: bool = False

    # Populated after assignment
    option_key: str | None = None
    assignment_method: AssignmentMethod | None = None
    assignment_confidence: float = 0.0
    requires_review: bool = True  # default safe
    risk_flags: list[str] = field(default_factory=list)

    @staticmethod
    def generate_region_id(page: int, bbox: tuple | None, source: str = "vl") -> str:
        """Deterministic region ID for dedup and audit."""
        raw = f"{source}_p{page}_{bbox or 'nobbox'}"
        return f"vr_{hashlib.md5(raw.encode()).hexdigest()[:12]}"

    def _coord_value(self) -> str | None:
        """Get coordinate space value regardless of storage type."""
        if self.coordinate_space is None:
            return None
        if isinstance(self.coordinate_space, CoordinateSpace):
            return self.coordinate_space.value
        return str(self.coordinate_space)

    def to_segment(self) -> dict:
        """Convert to a content segment dict for serialization."""
        seg: dict = {
            "type": (
                SegmentType.TABLE_IMAGE.value
                if self.region_type == VisualRegionType.TABLE
                else SegmentType.IMAGE.value
            ),
            "url": self.image_url,
            "alt": self.alt or "",
            "region_type": self.region_type.value,
            "region_id": self.region_id,
            "source_page": self.source_page,
            "bbox": list(self.bbox) if self.bbox else None,
            "coordinate_space": self._coord_value(),
            "confidence": self.confidence,
            "requires_review": self.requires_review,
            "display": True,
        }
        if self.option_key:
            seg["option_key"] = self.option_key
        return seg

    def to_dict(self) -> dict:
        """Full serialization for persistence.

        Table regions retain a bounded provider payload so the later
        ``table_detect`` stage can reconstruct rows/cells after OCR blocks have
        been released from memory.
        """
        result = {
            "region_id": self.region_id,
            "region_type": self.region_type.value,
            "source_page": self.source_page,
            "bbox": list(self.bbox) if self.bbox else None,
            "coordinate_space": self._coord_value(),
            "image_url": self.image_url,
            "alt": self.alt,
            "confidence": self.confidence,
            "requires_review": self.requires_review,
            "option_key": self.option_key,
            "assignment_method": self.assignment_method.value if self.assignment_method else None,
            "assignment_confidence": self.assignment_confidence,
            "risk_flags": self.risk_flags,
            "crop_failed": self.crop_failed,
        }
        if self.region_type == VisualRegionType.TABLE and self.raw_data:
            result["table_source"] = _bounded_table_source(self.raw_data)
        return result


def _bounded_table_source(raw: dict) -> dict:
    """Keep only table-recovery fields and cap provider payload size."""
    allowed = {
        "type", "label", "category", "text", "markdown", "html",
        "table_html", "table_markdown", "content", "value", "alt", "url", "src",
        "bbox", "cell_bbox", "polygon", "confidence", "width", "height",
        "rows", "headers", "header", "cells", "tokens", "ocr_tokens",
        "row_span", "rowspan", "col_span", "colspan", "is_header",
        "alignment", "align", "style", "caption", "column_widths",
        "source_page", "source_pages", "page", "page_num", "coordinate_space",
        "region_id", "table_id", "schema_version", "source_format",
        "signals", "continuation", "table", "data", "structure",
        "raw_block", "raw_data",
    }

    def sanitize(value, depth: int = 0):
        # A normal table payload reaches depth five at ``rows[].cells[].text``.
        # Leave enough room for rich cell content while still bounding hostile
        # or accidentally recursive provider data.
        if depth > 8:
            return None
        if isinstance(value, str):
            return value[:50000]
        if isinstance(value, (int, float, bool)) or value is None:
            return value
        if isinstance(value, (list, tuple)):
            return [sanitize(item, depth + 1) for item in list(value)[:1000]]
        if isinstance(value, dict):
            return {
                str(key): sanitize(item, depth + 1)
                for key, item in value.items()
                if str(key) in allowed
            }
        return str(value)[:1000]

    return sanitize(raw) or {}


@dataclass
class SourceSnapshot:
    """Source snapshot for review/audit purposes.

    Used as source_snapshot_url on QuestionImport and Question.
    Never inserted into content.segments.
    """
    url: str | None = None
    page: int = 0
    bbox: tuple[float, float, float, float] | None = None
    coordinate_space: CoordinateSpace = CoordinateSpace.PDF_POINTS
    failed: bool = False
    is_full_page: bool = False  # True when bbox couldn't be determined


# ---------------------------------------------------------------------------
# Visual reference detection patterns
# ---------------------------------------------------------------------------

_VISUAL_REFERENCE_PATTERNS = [
    "如图", "如下图", "图中", "见图", "如图所示",
    "根据图示", "如下表", "如下所示", "观察下列结构",
    "上图", "下图", "表", "表格", "示意图",
    "从图中", "由图中", "由图可知", "由表可知",
    "根据图", "根据下表", "根据上表",
]


def contains_visual_reference(text: str | None) -> bool:
    """Check if text contains phrases that reference visual elements."""
    if not text:
        return False
    for pat in _VISUAL_REFERENCE_PATTERNS:
        if pat in text:
            return True
    return False


# ---------------------------------------------------------------------------
# Risk flags for visual content
# ---------------------------------------------------------------------------

VISUAL_RISK_FLAGS = frozenset({
    "visual_reference_but_image_missing",
    "visual_region_bbox_missing",
    "visual_crop_failed",
    "visual_region_ambiguous",
    "visual_insert_position_uncertain",
    "option_image_requires_review",
    "visual_region_unassigned",
    "source_snapshot_failed",
    "math_image_bbox_missing",
    "math_image_crop_failed",
})

VISUAL_BLOCKING_FLAGS = frozenset({
    "visual_reference_but_image_missing",
    "visual_region_bbox_missing",
    "visual_crop_failed",
    "visual_region_ambiguous",
    "visual_region_unassigned",
    "math_image_bbox_missing",
    "math_image_crop_failed",
    "option_image_requires_review",
})


def get_blocking_risk_flags(risk_flags: list[str]) -> list[str]:
    """Return subset of risk_flags that should block auto-publish."""
    return [f for f in risk_flags if f in VISUAL_BLOCKING_FLAGS]


# ---------------------------------------------------------------------------
# Segment builders
# ---------------------------------------------------------------------------


def make_text_segment(text: str) -> dict:
    return {"type": SegmentType.TEXT.value, "text": text}


def make_newline_segment() -> dict:
    return {"type": SegmentType.NEWLINE.value}


def make_image_segment(
    url: str,
    *,
    alt: str = "",
    region_type: str = "diagram",
    source_page: int = 0,
    bbox: list[float] | None = None,
    coordinate_space: str | None = None,
    region_id: str | None = None,
    confidence: float = 1.0,
    requires_review: bool = False,
    display: bool = True,
    option_key: str | None = None,
) -> dict:
    seg: dict = {
        "type": SegmentType.IMAGE.value,
        "url": url,
        "alt": alt,
        "region_type": region_type,
        "source_page": source_page,
        "bbox": bbox,
        "coordinate_space": coordinate_space,
        "confidence": confidence,
        "requires_review": requires_review,
        "display": display,
    }
    if region_id:
        seg["region_id"] = region_id
    if option_key:
        seg["option_key"] = option_key
    return seg


def make_math_image_segment(
    url: str | None,
    *,
    alt: str = "",
    source_page: int = 0,
    bbox: list[float] | None = None,
    confidence: float = 0.5,
    requires_review: bool = True,
    display: bool = True,
) -> dict:
    return {
        "type": SegmentType.MATH_IMAGE.value,
        "url": url,
        "alt": alt,
        "source_page": source_page,
        "bbox": bbox,
        "confidence": confidence,
        "requires_review": requires_review,
        "display": display,
    }


ALLOWED_SEGMENT_TYPES = frozenset(t.value for t in SegmentType)
