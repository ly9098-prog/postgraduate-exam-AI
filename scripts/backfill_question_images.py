#!/usr/bin/env python3
"""Backfill content images and source snapshots for data-structure PDF import.

两类图片资源：

1. Content images (regions → segments)
   - 只截取图/树/表/图结构
   - 写入 parsed_content.segments，供学生做题页面展示
   - 使用 get_question_assets_storage() 存储

2. Source snapshots (source_snapshot_*)
   - 包含题干、图形和完整选项
   - 写入 parsed_content 顶层字段，仅后台审核
   - 使用 get_question_assets_storage() 存储

Usage:
    # Dry-run (default): 生成本地 preview + HTML review report, 不碰 DB
    python scripts/backfill_question_images.py \\
        --db sqlite+aiosqlite:///./postgraduate.db \\
        --pdf artifacts/data-structure-import/source/ds_sc.pdf \\
        --dry-run --report /tmp/backfill-review.html

    # Apply: upload images + update DB
    python scripts/backfill_question_images.py \\
        --db sqlite+aiosqlite:///./postgraduate.db \\
        --pdf artifacts/data-structure-import/source/ds_sc.pdf \\
        --apply --report /tmp/backfill-report.json

    # Single question debug
    python scripts/backfill_question_images.py \\
        --db sqlite+aiosqlite:///./postgraduate.db \\
        --pdf <pdf> --only-question 229 --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("backfill_images")

# Ensure backend importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import fitz

# ── Constants ──

SUBJECT_ID = 7
SOURCE_FILE = "ds_sc.pdf"

# 27 image-dependent question numbers from next_task.md
ALL_IMAGE_QNOS = [
    229, 337, 343, 345, 346, 347, 365, 369, 371, 378, 379, 380,
    388, 395, 397, 400, 402, 405, 407, 408, 411, 412,
    451, 457, 460, 461, 472, 480,
]

# Questions that already have bbox in question-image-regions.json
KNOWN_BBOX_QNOS = {229, 369, 371, 380, 388, 395, 397, 400, 402, 405, 407,
                   411, 412, 451, 457, 460, 461, 472, 480}

# Questions without pre-defined bbox (need auto-localization)
AUTO_QNOS = set(ALL_IMAGE_QNOS) - KNOWN_BBOX_QNOS  # {337, 343, 345, 346, 347, 365, 378, 379, 408}

REGIONS_JSON = "/home/lmh/projects/postgraduate-ai/artifacts/data-structure-import/question-image-regions.json"
OCR_RESULTS_PATH = "/home/lmh/projects/postgraduate-ai/artifacts/data-structure-import/ocr_results.json"

# Visual reference keywords for placement
_VISUAL_KW = ["如下图", "下图所示", "下图", "如图所示", "如图", "图G",
              "图中", "见图", "如下所示", "如下表", "下图中"]

# Brand header patterns for pollution detection
_BRAND_RE = re.compile(r"风中易小生|24考研|WD数据结构|做题本|微信公众号|选择题】")

# Next-question pattern
_NEXT_Q_RE = re.compile(r"^\s*\d+\s*[.、)）]")

# ── Quality thresholds ──
CONTENT_MIN_W = 80
CONTENT_MIN_H = 50
CONTENT_MIN_BYTES = 1024
CONTENT_MAX_BLANK_RATIO = 0.95
CONTENT_MIN_NONWHITE_RATIO = 0.02

SNAPSHOT_MIN_W = 300
SNAPSHOT_MIN_H = 120
SNAPSHOT_MIN_BYTES = 4096

CONF_AUTO = 0.85
CONF_REVIEW = 0.65

# ── Dual-bbox / visual-text constants ──
CROP_VERSION = "visual-v2.1"       # increment when crop algorithm changes
OVERLAP_THRESHOLD = 0.6             # OCR lines with ≥ this ratio inside visual_bbox → visual_text
VISUAL_PADDING_PT = 12.0            # padding around diagram for content image (pdf_points)
CONTENT_FOREGROUND_SCAN_DPI = 150   # DPI for foreground scan (lower = faster)
CONTENT_FOREGROUND_MIN_RATIO = 0.005  # minimum non-white pixel fraction to count as "has content"

# ── OCR line zone classification ──
_ZONE_HEADER = "header"
_ZONE_FOOTER = "footer"
_ZONE_SECTION_HEADING = "section_heading"
_ZONE_ANSWER_HINT = "answer_hint"
_ZONE_QUESTION_STEM = "question_stem"
_ZONE_OPTION = "option"
_ZONE_VISUAL_TEXT = "visual_text"
_ZONE_BODY = "body"
_ZONE_NEXT_QUESTION = "next_question"

# ── Multi-signal header hints ──
# strong_hints: alone + top position → strong header signal
_HEADER_STRONG_HINTS = frozenset({
    "风中易小生", "WD数据结构",
})
# weak_hints: only count when combined with top position AND cross-page repetition
_HEADER_WEAK_HINTS = frozenset({
    "24考研计算机", "24考研", "做题本", "微信公众号",
})

# Answer-hint keywords (distinct from header)
_ANSWER_HINT_RE = re.compile(r"本部分答案在书|参考答案|答案在书", re.UNICODE)

# Pattern for option lines
_OPTION_LINE_RE = re.compile(r"^[A-D]\s*[.、:：)）]")

# Section heading patterns (章节标题)
_SECTION_HEADING_RE = re.compile(
    r'^[一二三四五六七八九十]+[、.．]'  # 一、 二. 等
    r'|^第[一二三四五六七八九十]+[章节篇]'  # 第一章 等
)

# Page number patterns
_PAGE_NUM_RE = re.compile(r'^[-—]?\d+\s*$')

# ── Manual bbox config path (versioned JSON, overrides JSON manifest) ──
_MANUAL_BBOX_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "..",
    "artifacts/backfill/ds_sc/manual-bboxes-v2.json",
)

# Stem/option analysis margins
_STEM_BOTTOM_MARGIN_PT = 4.0   # gap below stem text before diagram
_OPTION_TOP_MARGIN_PT = 4.0    # gap above first option before diagram


# ── Data types ──


@dataclass
class RegionDef:
    qno: int
    page: int
    region_id: str
    bbox: tuple[float, float, float, float]  # pdf_points
    coord_space: str = "pdf_points"
    region_type: str = "diagram"
    order: int = 0
    placement: str = "after_stem"
    confidence: float = 1.0
    requires_review: bool = False
    note: str = ""


@dataclass
class TargetRecord:
    id: int
    qno: int
    page: int
    status: str
    question_id: int | None
    parsed_content: dict
    batch_id: str
    source_file: str


@dataclass
class ImageResult:
    success: bool = False
    png: bytes | None = None
    width: int = 0
    height: int = 0
    file_size: int = 0
    blank_ratio: float = 1.0
    nonwhite_ratio: float = 0.0
    storage_key: str = ""
    url: str = ""
    error: str = ""
    has_header: bool = False
    has_next_q: bool = False
    requires_review: bool = False


@dataclass
class ZoneResult:
    """OCR line classification result with multi-signal confidence.

    Attributes:
        zone: One of _ZONE_HEADER, _ZONE_FOOTER, etc.
        confidence: Signal strength in [0, 1]; ≥0.7 = reliable, <0.3 = uncertain.
        matched_features: What signals fired (for diagnostics).
        excluded_from_question_text: Whether this line should be excluded
            when building cleaned stem text.
        exclude_reason: Human-readable reason if excluded.
        text: The original OCR text for this line.
        bbox_pt: The original bbox for this line.
    """
    zone: str = _ZONE_BODY
    confidence: float = 0.0
    matched_features: list[str] = field(default_factory=list)
    excluded_from_question_text: bool = False
    exclude_reason: str = ""
    text: str = ""
    bbox_pt: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)


# ── Zone whitelist: lines matching these zones are included in stem text ──
_STEM_ZONE_WHITELIST = frozenset({
    _ZONE_QUESTION_STEM,
})


def _is_question_stem_zone(zr: ZoneResult) -> bool:
    """Check if a ZoneResult should contribute to stem text."""
    return zr.zone in _STEM_ZONE_WHITELIST


# ── Document profile for cross-page repeated text detection ──


@dataclass
class HeaderSignature:
    """A normalized header/footer text signature found at a stable page position."""
    normalized_text: str
    raw_text: str
    typical_y0: float  # normalized y0 (0=top, 1=bottom)
    typical_y1: float
    page_count: int   # how many pages this appears on
    avg_bbox_left: float
    avg_bbox_width: float


class DocumentProfile:
    """Builds a profile of repeated headers/footers by scanning PDF pages.

    Used as input to multi-signal zone classification.  Construct once
    at the start of main() and pass to classify_ocr_lines().

    The profile is built by:
    1. Rendering the first *scan_pages* pages of the PDF
    2. Extracting top and bottom text blocks via PyMuPDF
    3. Normalizing text (NFKC, collapse whitespace)
    4. Finding text that repeats across pages at stable positions
    """

    def __init__(
        self,
        *,
        header_signatures: list[HeaderSignature] | None = None,
        footer_signatures: list[HeaderSignature] | None = None,
        known_brand_texts: list[str] | None = None,
    ):
        self.header_signatures = header_signatures or []
        self.footer_signatures = footer_signatures or []
        self.known_brand_texts = known_brand_texts or []

    @classmethod
    def from_pdf(
        cls,
        pdf_path: str,
        *,
        scan_pages: int = 20,
        page_rect_width: float | None = None,
    ) -> "DocumentProfile":
        """Scan the first *scan_pages* pages of a PDF for repeated headers."""
        import fitz as _fitz

        try:
            doc = _fitz.open(pdf_path)
        except Exception:
            logger.warning("DocumentProfile: cannot open %s", pdf_path)
            return cls()

        pages_to_scan = min(scan_pages, len(doc))
        if pages_to_scan < 3:
            doc.close()
            return cls()

        # For each page, collect top and bottom text blocks
        top_texts: list[dict] = []  # [{text, y0, y1, x0, x1, page}]
        bot_texts: list[dict] = []

        for i in range(pages_to_scan):
            p = doc[i]
            pr = p.rect
            blocks = p.get_text("blocks")
            for b in blocks:
                x0, y0, x1, y1, text, *_ = b
                if not text or not text.strip():
                    continue
                text = text.strip()
                # Top zone: y0 < 15% of page height
                if y0 < pr.height * 0.15:
                    top_texts.append({
                        "text": text,
                        "y0": y0, "y1": y1,
                        "x0": x0, "x1": x1,
                        "page": i,
                        "norm": cls._normalize(text),
                    })
                # Bottom zone: y1 > 85% of page height
                if y1 > pr.height * 0.85:
                    bot_texts.append({
                        "text": text,
                        "y0": y0, "y1": y1,
                        "x0": x0, "x1": x1,
                        "page": i,
                        "norm": cls._normalize(text),
                    })

        doc.close()

        # Find repeated texts
        header_sigs = cls._build_signatures(top_texts, pages_to_scan)
        footer_sigs = cls._build_signatures(bot_texts, pages_to_scan)

        logger.info(
            "DocumentProfile: scanned %d pages, %d header sigs, %d footer sigs",
            pages_to_scan, len(header_sigs), len(footer_sigs),
        )

        return cls(
            header_signatures=header_sigs,
            footer_signatures=footer_sigs,
        )

    @classmethod
    def from_ocr_data(
        cls,
        ocr_pages: dict[str, dict],
        pdf_rect,
    ) -> "DocumentProfile":
        """Build profile from pre-computed OCR data (pages -> OCR blocks)."""
        top_texts: list[dict] = []
        pages_scanned = 0
        ph = pdf_rect.height

        for page_key, page_data in ocr_pages.items():
            lines = page_data.get("lines", [])
            img_h = page_data.get("image_size", {}).get("height", 0)
            if img_h == 0:
                continue
            scale_y = ph / img_h
            for line in lines:
                text = line.get("text", "").strip()
                if not text:
                    continue
                y0 = line["bbox"][1] * scale_y
                y1 = line["bbox"][3] * scale_y
                if y0 < ph * 0.15:
                    top_texts.append({
                        "text": text,
                        "y0": y0, "y1": y1,
                        "page": pages_scanned,
                        "norm": cls._normalize(text),
                    })
            pages_scanned += 1

        header_sigs = cls._build_signatures(top_texts, max(pages_scanned, 1))
        return cls(header_signatures=header_sigs)

    @staticmethod
    def _normalize(text: str) -> str:
        """NFKC normalize, collapse whitespace, strip punctuation."""
        t = unicodedata.normalize("NFKC", text)
        t = re.sub(r'\s+', '', t)  # collapse all whitespace
        t = t.strip()
        return t

    @staticmethod
    def _build_signatures(
        texts: list[dict],
        total_pages: int,
        min_repeat_ratio: float = 0.3,
    ) -> list[HeaderSignature]:
        """Find texts that repeat across pages at stable positions."""
        if not texts:
            return []

        # Group by normalized text
        groups: dict[str, list[dict]] = {}
        for t in texts:
            norm = t["norm"]
            if not norm:
                continue
            groups.setdefault(norm, []).append(t)

        sigs = []
        for norm, items in groups.items():
            repeat_ratio = len(items) / total_pages
            if repeat_ratio < min_repeat_ratio:
                continue
            avg_y0 = sum(it["y0"] for it in items) / len(items)
            avg_y1 = sum(it["y1"] for it in items) / len(items)
            sigs.append(HeaderSignature(
                normalized_text=norm,
                raw_text=items[0]["text"],
                typical_y0=avg_y0,
                typical_y1=avg_y1,
                page_count=len(items),
                avg_bbox_left=0.0,
                avg_bbox_width=0.0,
            ))

        sigs.sort(key=lambda s: s.page_count, reverse=True)
        return sigs

    def is_header_signature(self, text: str, y0: float, page_height: float) -> bool:
        """Check if *text* at *y0* matches a known header signature."""
        if not self.header_signatures:
            return False
        norm = self._normalize(text)
        if not norm:
            return False
        # Must be in the top zone
        if y0 > page_height * 0.15:
            return False
        for sig in self.header_signatures:
            if norm == sig.normalized_text:
                return True
        return False

    def is_footer_signature(self, text: str, y1: float, page_height: float) -> bool:
        """Check if *text* at *y1* matches a known footer signature."""
        if not self.footer_signatures:
            return False
        norm = self._normalize(text)
        if not norm:
            return False
        if y1 < page_height * 0.85:
            return False
        for sig in self.footer_signatures:
            if norm == sig.normalized_text:
                return True
        return False


@dataclass
class QuestionReport:
    qno: int
    page: int
    record_id: int
    status: str
    question_id: int | None
    regions: list[dict] = field(default_factory=list)
    region_errors: list[str] = field(default_factory=list)
    snapshot_result: dict | None = None
    strategy: str = ""
    confidence: float = 0.0
    requires_review: bool = False
    warnings: list[str] = field(default_factory=list)
    db_updated: bool = False
    q_updated: bool = False

    # ── Identifier fields (no ambiguity) ──
    question_import_id: int = 0
    source_question_no: int = 0
    batch_id: str = ""
    is_published: bool = False

    # ── Page tracking (original vs resolved) ──
    db_source_page: int = 0
    configured_pdf_page: int | None = None
    resolved_pdf_page: int = 0
    page_resolution_strategy: str = "default"
    page_confidence: float = 1.0

    # ── Bbox source ──
    bbox_source: str = "unknown"

    # ── Content preview ──
    content_preview: str = ""

    # ── Dual-bbox / stem-cleanup diagnostics ──
    original_stem: str = ""
    cleaned_stem: str = ""
    excluded_visual_text: list[dict] = field(default_factory=list)
    visual_bbox: list[float] | None = None
    question_bbox: list[float] | None = None
    content_quality_issues: list[str] = field(default_factory=list)
    crop_version: str = ""


# ── Quality validation ──


def validate_image(img: ImageResult) -> None:
    """Quality gate for rendered images."""
    if not img.png:
        img.success = False
        img.error = "no image data"
        return
    try:
        from PIL import Image as PILImage
        import io
        pil = PILImage.open(io.BytesIO(img.png)).convert("RGB")
        pixels = list(pil.getdata())
        total = len(pixels)
        blank = sum(1 for r, g, b in pixels if r > 248 and g > 248 and b > 248)
        img.blank_ratio = blank / total if total else 1.0
        nonwhite = sum(1 for r, g, b in pixels if r < 250 or g < 250 or b < 250)
        img.nonwhite_ratio = nonwhite / total if total else 0.0
    except Exception as e:
        img.success = False
        img.error = f"validation error: {e}"


def check_header_pollution(png: bytes) -> bool:
    """Detect brand header in rendered image."""
    if not png or len(png) < 512:
        return False
    try:
        import io
        from PIL import Image
        img = Image.open(io.BytesIO(png)).convert("RGB")
        w, h = img.size
        if h < 30:
            return False
        top_strip = img.crop((0, 0, w, max(1, h // 6)))
        pixels = list(top_strip.getdata())
        colored = sum(1 for r, g, b in pixels if r < 200 or g < 200 or b < 200)
        return colored > len(pixels) * 0.25
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════
# Dual-bbox: visual_bbox computation (tight diagram crop)
# ═══════════════════════════════════════════════════════════════════


def compute_visual_bbox_from_foreground(
    pdf_path: str,
    page_num: int,
    region_bbox_pt: tuple[float, float, float, float],
    pdf_rect,
    *,
    padding_pt: float = 8.0,
    scan_dpi: int = 150,
    ocr_lines_pt: list[dict] | None = None,
    analysis_range_pt: tuple[float | None, float | None] | None = None,
) -> tuple[float, float, float, float]:
    """Refine a content region bbox to tightly enclose only the diagram area.

    Two strategies, tried in order:
    1. **OCR-based**: if *ocr_lines_pt* is provided, find diagram-internal
       text (short number/label lines) and use their union bbox — but only
       within *analysis_range_pt* if given.
    2. **Foreground pixel analysis**: column/row projection + row-density
       clustering to find the dense diagram band — restricted to
       *analysis_range_pt* if given.

    *analysis_range_pt* is (y0, y1) in pdf_points restricting where
    diagram content is searched.  Set to (stem_bottom + margin,
    first_option_top - margin) to exclude header/stem/options.

    Falls back to padded *region_bbox_pt* if both methods fail.
    """
    # ── Apply analysis range to region bbox ──
    rx0, ry0, rx1, ry1 = region_bbox_pt
    if analysis_range_pt:
        ay0, ay1 = analysis_range_pt
        if ay0 is not None:
            ry0 = max(ry0, ay0)
        if ay1 is not None:
            ry1 = min(ry1, ay1)
    # If range collapsed, fall back
    if ry1 <= ry0 + 10:
        return _padded_bbox(region_bbox_pt, padding_pt)

    restricted_region = (rx0, ry0, rx1, ry1)

    # ── Strategy 1: OCR-based diagram extent ──
    if ocr_lines_pt:
        diagram_bbox = _ocr_diagram_bbox(ocr_lines_pt, restricted_region, pdf_rect.height)
        if diagram_bbox is not None:
            return _clamp_visual_to_region(diagram_bbox, restricted_region, padding_pt)

    # ── Strategy 2: Foreground pixel analysis ──
    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return _padded_bbox(restricted_region, padding_pt)
    try:
        if page_num < 1 or page_num > len(doc):
            return _padded_bbox(restricted_region, padding_pt)
        p = doc[page_num - 1]
        clip = fitz.Rect(*restricted_region)
        pix = p.get_pixmap(dpi=scan_dpi, clip=clip, alpha=False)
        w, h = pix.width, pix.height
        if w < 4 or h < 4:
            return _padded_bbox(restricted_region, padding_pt)

        samples = pix.samples
        stride = w * 3
        row_nonwhite = []
        col_nonwhite = [0] * w

        for y in range(h):
            row_count = 0
            for x in range(w):
                idx = y * stride + x * 3
                r, g, b = samples[idx], samples[idx + 1], samples[idx + 2]
                is_ink = r < 248 or g < 248 or b < 248
                if is_ink:
                    row_count += 1
                    col_nonwhite[x] += 1
            row_nonwhite.append(row_count)

        max_col = max(col_nonwhite) if col_nonwhite else 0
        col_thresh = max_col * 0.02
        x_start = next((x for x in range(w) if col_nonwhite[x] > col_thresh), 0)
        x_end = next((x for x in range(w - 1, -1, -1) if col_nonwhite[x] > col_thresh), w - 1)

        ink_total = sum(row_nonwhite)
        avg_density = ink_total / (h * w) if h * w > 0 else 0
        diagram_thresh = max(avg_density * w * 2.0, w * 0.05)

        # Find dense bands, keep the WIDEST one (diagram is typically largest)
        dense_ranges = []
        in_dense = False
        range_start = 0
        for y in range(h):
            is_dense = row_nonwhite[y] > diagram_thresh
            if is_dense and not in_dense:
                range_start = y
                in_dense = True
            elif not is_dense and in_dense:
                # Allow small gaps (1-3 rows)
                gap_ok = True
                for yy in range(y, min(y + 5, h)):
                    if row_nonwhite[yy] > diagram_thresh:
                        gap_ok = False
                        break
                if not gap_ok:
                    continue
                dense_ranges.append((range_start, y - 1))
                in_dense = False
        if in_dense:
            dense_ranges.append((range_start, h - 1))

        if dense_ranges:
            dense_ranges.sort(key=lambda r: r[1] - r[0], reverse=True)
            y_start, y_end = dense_ranges[0]
        else:
            y_start, y_end = 0, h - 1

        scale_x = clip.width / w
        scale_y = clip.height / h

        visual_pt = (
            clip.x0 + x_start * scale_x,
            clip.y0 + y_start * scale_y,
            clip.x0 + x_end * scale_x,
            clip.y0 + y_end * scale_y,
        )
        return _clamp_visual_to_region(visual_pt, restricted_region, padding_pt)
    finally:
        doc.close()


def _ocr_diagram_bbox(
    ocr_lines_pt: list[dict],
    region_bbox_pt: tuple[float, float, float, float],
    page_height: float,
) -> tuple[float, float, float, float] | None:
    """Compute diagram bbox from pre-computed OCR lines.

    Finds OCR lines inside the target region that are short (≤6 chars)
    and classified as visual_text — these are diagram node labels.
    Returns union bbox, or None if insufficient diagram lines found.
    """
    rx0, ry0, rx1, ry1 = region_bbox_pt
    diagram_bboxes: list[tuple[float, float, float, float]] = []

    for line in ocr_lines_pt:
        b = line["bbox_pt"]
        text = line.get("text", "").strip()

        # Must overlap with region
        if b[2] <= rx0 or b[0] >= rx1 or b[3] <= ry0 or b[1] >= ry1:
            continue
        if len(text) > 6:
            continue
        # Use multi-signal classifier to skip non-diagram zones
        zr = classify_line(line, page_height)
        if zr.zone in (_ZONE_HEADER, _ZONE_QUESTION_STEM, _ZONE_OPTION, _ZONE_FOOTER, _ZONE_ANSWER_HINT):
            continue
        diagram_bboxes.append(b)

    if len(diagram_bboxes) < 2:
        return None

    return (
        min(b[0] for b in diagram_bboxes),
        min(b[1] for b in diagram_bboxes),
        max(b[2] for b in diagram_bboxes),
        max(b[3] for b in diagram_bboxes),
    )


def _padded_bbox(
    bbox: tuple[float, float, float, float],
    padding_pt: float,
) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = bbox
    return (x0 - padding_pt, y0 - padding_pt, x1 + padding_pt, y1 + padding_pt)


def _clamp_visual_to_region(
    visual: tuple[float, float, float, float],
    region: tuple[float, float, float, float],
    padding_pt: float,
) -> tuple[float, float, float, float]:
    """Apply padding to visual bbox and clamp it inside the region bbox."""
    vx0, vy0, vx1, vy1 = visual
    rx0, ry0, rx1, ry1 = region
    return (
        max(rx0, vx0 - padding_pt),
        max(ry0, vy0 - padding_pt),
        min(rx1, vx1 + padding_pt),
        min(ry1, vy1 + padding_pt),
    )


def refine_visual_bbox_for_options(
    visual_bbox_pt: tuple[float, float, float, float],
    first_option_top_pt: float | None,
    region_bbox_pt: tuple[float, float, float, float],
    *,
    min_gap_pt: float = 4.0,
) -> tuple[float, float, float, float]:
    """Ensure visual_bbox doesn't extend into option text area.

    If the visual bbox's bottom edge is below or too close to the first
    option line, trim it to stay strictly above.
    """
    if first_option_top_pt is None:
        return visual_bbox_pt
    _, _, _, vbottom = visual_bbox_pt
    if vbottom >= first_option_top_pt - min_gap_pt:
        # Trim to keep gap
        new_bottom = max(first_option_top_pt - min_gap_pt, region_bbox_pt[1])
        return (visual_bbox_pt[0], visual_bbox_pt[1], visual_bbox_pt[2], new_bottom)
    return visual_bbox_pt


# ═══════════════════════════════════════════════════════════════════
# OCR overlap analysis and stem cleanup (spatial dedup)
# ═══════════════════════════════════════════════════════════════════


def load_precomputed_ocr(
    ocr_path: str,
) -> dict[str, dict]:
    """Load pre-computed OCR results (from PP-OCR / MCP tool)."""
    if not os.path.isfile(ocr_path):
        logger.info("No pre-computed OCR file at %s", ocr_path)
        return {}
    with open(ocr_path) as f:
        return json.load(f)


def ocr_lines_to_pdf_points(
    ocr_lines: list[dict],
    image_size: tuple[int, int],
    pdf_rect: fitz.Rect,
) -> list[dict]:
    """Convert OCR line bboxes from image pixels to PDF points."""
    img_w, img_h = image_size
    pw, ph = pdf_rect.width, pdf_rect.height
    scale_x = pw / img_w
    scale_y = ph / img_h
    out = []
    for line in ocr_lines:
        b = line["bbox"]
        out.append({
            "text": line["text"],
            "confidence": line.get("confidence", 0.0),
            "bbox_pixels": tuple(b),
            "bbox_pt": (
                b[0] * scale_x,
                b[1] * scale_y,
                b[2] * scale_x,
                b[3] * scale_y,
            ),
        })
    return out


def compute_overlap_ratio(
    line_bbox_pt: tuple[float, float, float, float],
    visual_bbox_pt: tuple[float, float, float, float],
) -> float:
    """Compute intersection-over-area of an OCR line bbox vs visual_bbox.

    Returns overlap_ratio in [0.0, 1.0].
    """
    lx0, ly0, lx1, ly1 = line_bbox_pt
    vx0, vy0, vx1, vy1 = visual_bbox_pt

    ix0 = max(lx0, vx0)
    iy0 = max(ly0, vy0)
    ix1 = min(lx1, vx1)
    iy1 = min(ly1, vy1)

    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0

    inter_area = (ix1 - ix0) * (iy1 - iy0)
    line_area = (lx1 - lx0) * (ly1 - ly0)
    if line_area <= 0:
        return 0.0
    return inter_area / line_area


def analyze_ocr_overlap(
    ocr_lines_pt: list[dict],
    visual_bbox_pt: tuple[float, float, float, float],
    *,
    threshold: float = OVERLAP_THRESHOLD,
) -> tuple[list[dict], list[dict]]:
    """Compute overlap ratio for each OCR line against visual_bbox.

    Returns (visual_text_lines, kept_lines):
    - visual_text_lines: lines with overlap_ratio >= threshold
    - kept_lines: lines with overlap_ratio < threshold (or non-overlapping)
    """
    visual_text: list[dict] = []
    kept: list[dict] = []
    for line in ocr_lines_pt:
        ratio = compute_overlap_ratio(line["bbox_pt"], visual_bbox_pt)
        annotated = dict(line)
        annotated["overlap_ratio"] = round(ratio, 4)
        if ratio >= threshold:
            annotated["zone"] = "visual_text"
            annotated["excluded_from_stem"] = True
            annotated["exclude_reason"] = "inside_visual_region"
            visual_text.append(annotated)
        else:
            annotated["zone"] = "body"
            annotated["excluded_from_stem"] = False
            kept.append(annotated)
    return visual_text, kept


def clean_stem_from_visual_text(
    stem_text: str,
    ocr_kept_lines: list[dict],
    ocr_viz_lines: list[dict],
) -> str:
    """Reconstruct stem text by excluding visual_text lines.

    Removes both whitespace-separated tokens and concatenated sequences
    of visual-text tokens from the stem.  Handles the case where OCR
    merges adjacent diagram node values without spaces (e.g. "151922"
    = "15"+"19"+"22").

    Returns cleaned stem text.
    """
    if not ocr_viz_lines:
        return stem_text

    excluded_tokens: list[str] = []
    for vl in ocr_viz_lines:
        t = vl["text"].strip()
        if t and len(t) <= 6:  # only short tokens (node values, labels)
            excluded_tokens.append(t)

    if not excluded_tokens:
        return stem_text

    excluded_tokens.sort(key=len, reverse=True)  # longest first

    import re as _re
    result = stem_text

    # Phase 1: remove whitespace-separated tokens found in excluded list
    # Build pattern: match token that has space before/after or is at boundary
    for token in excluded_tokens:
        if not token:
            continue
        # Remove token when surrounded by spaces or at string boundaries
        pat = _re.compile(
            r'(?<!\S)' + _re.escape(token) + r'(?!\S)',
        )
        result = pat.sub('', result)

    # Phase 2: remove concatenations of adjacent excluded tokens
    # Try all lengths from 2 to len(excluded_tokens)
    # Sort tokens by length ascending for concatenation
    st = sorted(excluded_tokens, key=len)  # shorter first for sub-concat
    concat_set: set[str] = set()
    for i in range(len(st)):
        for j in range(i + 1, min(i + 6, len(st))):
            # Try adjacent concatenations
            for k in range(j, min(j + 4, len(st))):
                concat = "".join(st[i:k+1])
                if concat and len(concat) > max(len(st[i]), len(st[k])):
                    concat_set.add(concat)

    # Sort by length descending so we match longest concatenations first
    for concat in sorted(concat_set, key=len, reverse=True):
        pat = _re.compile(
            r'(?<!\S)' + _re.escape(concat) + r'(?!\S)',
        )
        result = pat.sub('', result)

    # Phase 3: cleanup orphaned punctuation and extra spaces
    result = _re.sub(r'\(\s*\)\s*$', '()', result)  # trailing ()
    result = _re.sub(r'\(\s+', '(', result)
    result = _re.sub(r'\s+\)', ')', result)
    result = _re.sub(r'\(\s*,\s*\)', '()', result)
    result = _re.sub(r'\s{2,}', ' ', result)  # collapse multiple spaces
    result = result.strip()

    return result


def detect_first_option_pt(
    ocr_lines_pt: list[dict],
) -> float | None:
    """Find the PDF-points y-coordinate of the first option line (A/B/C/D)."""
    for line in ocr_lines_pt:
        text = line.get("text", "").strip()
        if _OPTION_LINE_RE.match(text):
            return line["bbox_pt"][1]
    return None


def detect_answer_hint(text: str) -> bool:
    """Check if text contains answer-page hint like '本部分答案在书'."""
    return bool(_ANSWER_HINT_RE.search(text))


# ═══════════════════════════════════════════════════════════════════
# OCR line classification and zone detection
# ═══════════════════════════════════════════════════════════════════


def _score_header_signals(
    text: str,
    y0: float,
    page_height: float,
    doc_profile: DocumentProfile | None = None,
) -> tuple[float, list[str]]:
    """Multi-signal header detection.

    Returns (score, matched_features) where score >= 2.0 = header,
    1.0-2.0 = probable header, < 1.0 = not header.

    Signals:
    - +3.0: normalized text matches a DocumentProfile header signature
            AND is in the top 15% of the page
    - +2.0: strong_hint keyword match AND in top 15%
    - +1.0: weak_hint keyword match AND in top 15%
    - +1.0: strong_hint keyword match (even if below top 15%, but rare)
    - -2.0: text contains Chinese sentence punctuation (likely body text)
    """
    features: list[str] = []
    score = 0.0
    is_top = y0 < page_height * 0.15

    # Signal 1: DocumentProfile signature match (strongest)
    if doc_profile and doc_profile.is_header_signature(text, y0, page_height):
        features.append("header_signature_match")
        score += 3.0

    # Signal 2: strong_hints
    for kw in _HEADER_STRONG_HINTS:
        if kw in text:
            if is_top:
                features.append(f"strong_hint+top:{kw}")
                score += 2.0
            else:
                features.append(f"strong_hint:{kw}")
                score += 1.0

    # Signal 3: weak_hints - only count if at top of page
    if is_top:
        for kw in _HEADER_WEAK_HINTS:
            if kw in text:
                features.append(f"weak_hint+top:{kw}")
                score += 1.0

    # Negative signal: contains Chinese sentence text (likely a real sentence)
    if re.search(r'[，。；：？、]', text):
        features.append("has_sentence_punct")
        score -= 2.0

    return score, features


def classify_line(
    line: dict,
    page_height: float,
    doc_profile: DocumentProfile | None = None,
) -> ZoneResult:
    """Multi-signal zone classification for a single OCR line.

    Combines position signals, content signals, and document profile to
    produce a ZoneResult with confidence score and matched features.
    """
    text = line.get("text", "").strip()
    bbox_pt = line.get("bbox_pt", (0, 0, 0, 0))
    y0, y1 = bbox_pt[1], bbox_pt[3]

    if not text:
        return ZoneResult(zone=_ZONE_BODY, confidence=0.0, excluded_from_question_text=False)

    # ── Signal: answer_hint ──
    if _ANSWER_HINT_RE.search(text):
        return ZoneResult(
            zone=_ZONE_ANSWER_HINT, confidence=0.95,
            matched_features=["answer_hint_regex"],
            excluded_from_question_text=True,
            exclude_reason="answer_hint",
        )

    # ── Signal: option line ──
    if _OPTION_LINE_RE.match(text):
        return ZoneResult(
            zone=_ZONE_OPTION, confidence=0.95,
            matched_features=["option_regex"],
            excluded_from_question_text=True,
            exclude_reason="option_line",
        )

    # ── Multi-signal header detection ──
    hdr_score, hdr_features = _score_header_signals(text, y0, page_height, doc_profile)
    if hdr_score >= 2.0:
        return ZoneResult(
            zone=_ZONE_HEADER, confidence=min(hdr_score / 4.0, 0.95),
            matched_features=hdr_features,
            excluded_from_question_text=True,
            exclude_reason="brand_header",
        )

    # ── Signal: section heading (章节标题) ──
    if _SECTION_HEADING_RE.match(text):
        return ZoneResult(
            zone=_ZONE_SECTION_HEADING, confidence=0.8,
            matched_features=["section_heading_regex"],
            excluded_from_question_text=False,
        )

    # ── Signal: page number (footer) ──
    if _PAGE_NUM_RE.match(text) and y1 > page_height * 0.85:
        return ZoneResult(
            zone=_ZONE_FOOTER, confidence=0.7,
            matched_features=["page_number+bottom"],
            excluded_from_question_text=True,
            exclude_reason="page_number",
        )

    # ── Signal: next question reference / question stem ──
    # Lines starting with a number prefix and containing Chinese content
    if re.match(r'^\d+\s*[.、)）【]', text):
        if len(text) <= 15 and not any('\u4e00' <= c <= '\u9fff' for c in text):
            # Short pure number prefix → next question reference
            return ZoneResult(
                zone=_ZONE_NEXT_QUESTION, confidence=0.7,
                matched_features=["next_question_reference"],
                excluded_from_question_text=True,
                exclude_reason="next_question_number",
            )
        # Has Chinese content → question stem
        return ZoneResult(
            zone=_ZONE_QUESTION_STEM, confidence=0.75,
            matched_features=["numbered_question_line"],
            excluded_from_question_text=False,
        )

    # Long text with Chinese characters → question stem or section
    if len(text) >= 10 or any(c > '\u4e00' for c in text):
        return ZoneResult(
            zone=_ZONE_QUESTION_STEM, confidence=0.6,
            matched_features=["long_chinese_text"],
            excluded_from_question_text=False,
        )

    # ── Signal: visual text (short labels in diagram area) ──
    if len(text) <= 6:
        return ZoneResult(
            zone=_ZONE_VISUAL_TEXT, confidence=0.5,
            matched_features=["short_label"],
            excluded_from_question_text=True,
            exclude_reason="visual_text_label",
        )

    return ZoneResult(
        zone=_ZONE_BODY, confidence=0.3,
        matched_features=["unclassified"],
        excluded_from_question_text=False,
    )


def classify_ocr_lines(
    ocr_lines_pt: list[dict],
    page_height: float,
    doc_profile: DocumentProfile | None = None,
) -> dict[str, list[ZoneResult]]:
    """Classify all OCR lines into zones using multi-signal approach.

    Returns dict mapping zone name to list of ZoneResult objects.
    """
    zones: dict[str, list[ZoneResult]] = {
        _ZONE_HEADER: [],
        _ZONE_FOOTER: [],
        _ZONE_SECTION_HEADING: [],
        _ZONE_ANSWER_HINT: [],
        _ZONE_QUESTION_STEM: [],
        _ZONE_OPTION: [],
        _ZONE_VISUAL_TEXT: [],
        _ZONE_BODY: [],
        _ZONE_NEXT_QUESTION: [],
    }
    for line in ocr_lines_pt:
        zr = classify_line(line, page_height, doc_profile)
        zr.text = line.get("text", "")
        zr.bbox_pt = line.get("bbox_pt", (0.0, 0.0, 0.0, 0.0))
        zones.setdefault(zr.zone, []).append(zr)
    return zones


def compute_stem_bottom_pt(
    ocr_lines_pt: list[dict],
    page_height: float,
    doc_profile: DocumentProfile | None = None,
) -> float | None:
    """Compute the bottom y-coordinate of question stem text."""
    if not ocr_lines_pt:
        return None
    max_bottom = None
    for oline in ocr_lines_pt:
        zr = classify_line(oline, page_height, doc_profile)
        if zr.zone == _ZONE_QUESTION_STEM:
            b = oline.get("bbox_pt", (0, 0, 0, 0))
            if max_bottom is None or b[3] > max_bottom:
                max_bottom = b[3]
    return max_bottom


def compute_diagram_zone_pt(
    ocr_lines_pt: list[dict],
    page_height: float,
    doc_profile: DocumentProfile | None = None,
    *,
    stem_gap_pt: float = 4.0,
    option_gap_pt: float = 4.0,
) -> tuple[float | None, float | None]:
    """Compute valid diagram analysis zone from OCR line classification."""
    zones = classify_ocr_lines(ocr_lines_pt, page_height, doc_profile)
    opt_lines = zones.get(_ZONE_OPTION, [])
    stem_bottom = compute_stem_bottom_pt(ocr_lines_pt, page_height, doc_profile)
    first_opt_top = detect_first_option_pt(ocr_lines_pt) if opt_lines else None
    zone_top = (stem_bottom + stem_gap_pt) if stem_bottom is not None else None
    zone_bot = (first_opt_top - option_gap_pt) if first_opt_top is not None else None
    return zone_top, zone_bot
# Content image quality gates
# ═══════════════════════════════════════════════════════════════════


def check_content_image_quality(
    png: bytes,
    *,
    ocr_texts: list[str] | None = None,
) -> list[str]:
    """Quality gate for content images. Returns list of issues found.

    Only checks the rendered image content (pixel analysis, dimensions).
    OCR-text-based checks are not available without re-OCR'ing the rendered
    clip — rely on the visual bbox to exclude unwanted text.
    """
    issues: list[str] = []
    if not png or len(png) < 512:
        issues.append("empty_or_tiny")
        return issues

    # Check brand header pollution in rendered image
    if check_header_pollution(png):
        issues.append("header_pollution")

    # Check dimension sanity
    try:
        import io
        from PIL import Image
        img = Image.open(io.BytesIO(png))
        w, h = img.size
        if w < 16 or h < 16:
            issues.append(f"too_small_{w}x{h}")
        if w > 2000 or h > 2000:
            issues.append(f"oversized_{w}x{h}")
    except Exception:
        issues.append("invalid_png")

    return issues


def check_visual_gate(
    bbox_pt: tuple[float, float, float, float],
    page_rect,
    *,
    stem_bottom_pt: float | None = None,
    first_option_top_pt: float | None = None,
    header_bottom_pt: float | None = None,
    margin_max_pt: float = 24.0,
) -> list[str]:
    """Hard visual quality gate — detects common failures in content images.

    Returns a list of failure reasons.  Empty list means the image passes
    all visual gates.
    """
    failures: list[str] = []
    x0, y0, x1, y1 = bbox_pt
    pw, ph = page_rect.width, page_rect.height

    # ── Coordinate sanity ──
    if x1 <= x0 or y1 <= y0:
        failures.append("invalid_bbox")
        return failures
    if x0 < 0 or y0 < 0 or x1 > pw or y1 > ph:
        failures.append("bbox_out_of_bounds")
        return failures

    # ── Near-full-page detection ──
    bbox_area = (x1 - x0) * (y1 - y0)
    page_area = pw * ph
    if page_area > 0 and bbox_area > page_area * 0.85:
        failures.append("bbox_near_full_page")
    if (x1 - x0) > pw * 0.95 or (y1 - y0) > ph * 0.85:
        failures.append("bbox_excessive_size")

    # ── Top too high (above stem) ──
    if stem_bottom_pt is not None and y0 < stem_bottom_pt:
        failures.append(f"top_above_stem(y0={y0:.1f} < stem_bottom={stem_bottom_pt:.1f})")

    # ── Bottom too low (into options) ──
    if first_option_top_pt is not None and y1 > first_option_top_pt:
        failures.append(f"bottom_below_options(y1={y1:.1f} > opt_top={first_option_top_pt:.1f})")

    # ── Header inclusion ──
    hdr_bot = header_bottom_pt or (page_rect.y0 + 28.0)
    if y0 < hdr_bot:
        failures.append(f"includes_header(y0={y0:.1f} < header_bottom={hdr_bot:.1f})")

    return failures


def check_visual_completeness(
    png: bytes,
    bbox_pt: tuple[float, float, float, float],
    *,
    ocr_visual_texts: list[dict] | None = None,
    min_fg_edge_margin_px: int = 2,
) -> list[str]:
    """Visual completeness gates for content images.

    Checks:
    1. **foreground_edge_touch**: No non-white pixels within *min_fg_edge_margin_px*
       of the crop boundary (diagram shouldn't be cut off).
    2. **visual_text_coverage**: All OCR lines classified as visual_text that
       spatially overlap with this bbox should be fully inside it.
    3. **edge_component_truncation**: Connected components touching the crop
       edge are likely truncated.

    Returns list of issues (empty = passes all gates).
    Any failure sets requires_review=True (cannot auto-pass).
    """
    issues: list[str] = []

    if not png or len(png) < 256:
        issues.append("completeness_no_image")
        return issues

    try:
        import io
        from PIL import Image
        img = Image.open(io.BytesIO(png)).convert("L")  # grayscale
        w, h = img.size
        pixels = list(img.getdata())

        # ── Gate 1: foreground edge proximity ──
        edge_touches = 0
        total_edge = 2 * (w + h) * min_fg_edge_margin_px
        for y in range(h):
            for x in range(w):
                if x < min_fg_edge_margin_px or x >= w - min_fg_edge_margin_px or                    y < min_fg_edge_margin_px or y >= h - min_fg_edge_margin_px:
                    idx = y * w + x
                    if idx < len(pixels) and pixels[idx] < 200:
                        edge_touches += 1
        if edge_touches > max(1, total_edge * 0.05):
            issues.append(f"foreground_edge_touch({edge_touches}px)")

        # ── Gate 2: connected component edge truncation ──
        # Check all four edges for non-white content suggesting truncation
        if h > 10:
            top_row_ink = sum(1 for x in range(w) if pixels[x] < 200)
            bottom_row_ink = sum(1 for x in range(w) if h * w - w + x < len(pixels) and pixels[h * w - w + x] < 200)
            if bottom_row_ink > w * 0.3:
                issues.append(f"edge_component_truncated(bottom_row={bottom_row_ink}/{w})")
            if top_row_ink > w * 0.3:
                issues.append(f"edge_component_truncated(top_row={top_row_ink}/{w})")
        if w > 10:
            left_col_ink = sum(1 for y in range(h) if y * w < len(pixels) and pixels[y * w] < 200)
            right_col_ink = sum(1 for y in range(h) if y * w + w - 1 < len(pixels) and pixels[y * w + w - 1] < 200)
            if right_col_ink > h * 0.3:
                issues.append(f"edge_component_truncated(right_col={right_col_ink}/{h})")
            if left_col_ink > h * 0.3:
                issues.append(f"edge_component_truncated(left_col={left_col_ink}/{h})")

        # ── Gate 3: visual_text coverage ──
        if ocr_visual_texts:
            uncovered = []
            for vt in ocr_visual_texts:
                vb = vt.get("bbox_pt")
                if not vb or len(vb) != 4:
                    continue
                overlap_ratio = compute_overlap_ratio(vb, bbox_pt)
                if overlap_ratio < 0.5:
                    uncovered.append(vt.get("text", "?"))
            if uncovered:
                issues.append(f"visual_text_coverage({len(uncovered)}/uncovered:{uncovered[:5]})")

    except Exception as e:
        issues.append(f"completeness_check_error:{e}")

    return issues


def content_storage_key(
    source_file: str,
    page: int,
    qno: int,
    bbox: tuple[float, float, float, float] | None,
    *,
    kind: str = "content",
    crop_version: str | None = CROP_VERSION,
) -> str:
    """Generate storage key including crop_version for regeneration support."""
    if bbox:
        bstr = f"{bbox[0]:.1f}_{bbox[1]:.1f}_{bbox[2]:.1f}_{bbox[3]:.1f}"
        raw = f"{source_file}_p{page}_q{qno}_{bstr}_{kind}"
        if crop_version:
            raw += f"_{crop_version}"
    else:
        raw = f"{source_file}_p{page}_q{qno}_{kind}"
    h = hashlib.md5(raw.encode()).hexdigest()[:12]
    m = datetime.now().strftime("%Y%m")
    ver = f"{crop_version}_" if crop_version else ""
    return f"{m}/{ver}ds_{h}_{kind}.png"


# ── Bbox normalization ──


def norm_bbox(bbox, page, padding_pt=0.0, top_padding=None, exclude_header=True):
    """Normalize bbox for page rotation/cropbox, apply padding, clamp to page.rect.

    Args:
        top_padding: override padding for top edge only (prevent header inclusion).
                     If None, uses padding_pt for all sides.
        exclude_header: If True, ensures bbox top starts below brand header zone
                        (below 15pt from page top for this specific PDF).
    """
    r = page.rect
    x0, y0, x1, y1 = bbox
    tp = top_padding if top_padding is not None else padding_pt

    # Apply padding
    x0 = max(r.x0, x0 - padding_pt)
    y0 = max(r.y0, y0 - tp)
    x1 = min(r.x1, x1 + padding_pt)
    y1 = min(r.y1, y1 + padding_pt)

    # Defensive header exclusion: force bbox top below brand header zone.
    # The brand banner on this PDF occupies roughly the top 8-15pt.
    if exclude_header:
        header_bottom = r.y0 + 28.0  # below header zone (banner is ~26pt)
        if y0 < header_bottom:
            y0 = header_bottom

    return (x0, y0, x1, y1)


# ── Rendering ──


def render_clip(
    pdf_path: str, page_num: int,
    bbox, *, dpi=220, padding_pt=0.0, max_side=3200,
    restrict_top_padding=False,
    render_bbox_as_is=False,
) -> ImageResult:
    """Render a clip from PDF page and validate quality.

    Args:
        restrict_top_padding: If True, minimal top padding (2pt) to avoid
                              including brand header in the clip.
        render_bbox_as_is: If True, use bbox directly without norm_bbox.
    """
    res = ImageResult()
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        res.error = f"cannot open PDF: {e}"
        return res
    try:
        if page_num < 1 or page_num > len(doc):
            res.error = f"page {page_num} out of range (1-{len(doc)})"
            return res
        p = doc[page_num - 1]
        top_pad = 2.0 if restrict_top_padding else padding_pt
        if bbox and len(bbox) == 4:
            if render_bbox_as_is:
                clip = fitz.Rect(*bbox)
            else:
                nb = norm_bbox(bbox, p, padding_pt, top_padding=top_pad)
                clip = fitz.Rect(*nb)
        else:
            clip = p.rect
        pix = p.get_pixmap(dpi=dpi, clip=clip, alpha=False)
        if max(pix.width, pix.height) > max_side:
            s = max_side / max(pix.width, pix.height)
            pix = p.get_pixmap(dpi=int(dpi * s), clip=clip, alpha=False)
        res.png = pix.tobytes("png")
        res.width = pix.width
        res.height = pix.height
        res.file_size = len(res.png)
        res.success = True
    except Exception as e:
        res.error = f"render error: {e}"
        return res
    finally:
        doc.close()
    validate_image(res)
    res.has_header = check_header_pollution(res.png) if res.png else False
    if res.has_header:
        res.requires_review = True
    return res


# ── Storage key (idempotent, versioned) ──


def storage_key(source_file, page, qno, bbox, kind="content"):
    """Legacy storage key — delegates to content_storage_key with crop_version."""
    return content_storage_key(source_file, page, qno, bbox, kind=kind)


# ── Region computation ──


def load_regions() -> dict:
    if not os.path.isfile(REGIONS_JSON):
        logger.warning("Regions JSON not found: %s", REGIONS_JSON)
        return {}
    with open(REGIONS_JSON) as f:
        return json.load(f)


def load_manual_bbox_config() -> dict[int, list[dict]]:
    """Load manual bbox overrides from versioned JSON config.

    Returns dict mapping qno → list of region dicts with keys:
        region_id, bbox, region_type, bbox_source, approved, note.
    Returns empty dict if config not found or invalid.
    """
    cfg_path = _MANUAL_BBOX_CONFIG_PATH
    if not os.path.isfile(cfg_path):
        logger.warning("Manual bbox config not found: %s", cfg_path)
        return {}
    try:
        with open(cfg_path) as f:
            cfg = json.load(f)
    except Exception as e:
        logger.warning("Cannot load manual bbox config: %s", e)
        return {}

    entries = cfg.get("entries", [])
    manual_map: dict[int, list[dict]] = {}
    for e in entries:
        qno = e.get("source_question_no")
        if qno is None:
            continue
        approved = e.get("approved", False)
        for reg in e.get("regions", []):
            manual_map.setdefault(qno, []).append({
                "region_id": reg.get("region_id", f"q{qno}_manual"),
                "bbox": reg.get("bbox", []),
                "region_type": reg.get("region_type", "diagram"),
                "order": reg.get("order", 0),
                "placement": reg.get("placement", "after_stem"),
                "bbox_source": e.get("bbox_source", "manual_unknown"),
                "approved": approved,
                "note": e.get("note", "manual_override"),
            })
    logger.info("Manual bbox config: %d entries loaded", len(manual_map))
    return manual_map


def regions_from_manifest(qno, page, entry, manual_map=None) -> list[RegionDef]:
    raw = entry.get("regions") or [entry]
    out = []
    manual_entries = (manual_map or {}).get(qno)
    for idx, r in enumerate(raw):
        if manual_entries:
            m = manual_entries[idx] if idx < len(manual_entries) else manual_entries[0]
            b = m["bbox"]
            rid = m.get("region_id", f"q{qno}_manual")
            rt = m.get("region_type", "diagram")
            order = m.get("order", idx)
            placement = m.get("placement", "after_stem")
            conf = 0.75 if m.get("approved") else 0.7
            verified = m.get("approved", False)
        else:
            b = r.get("bbox")
            if not b or len(b) != 4:
                continue
            rid = r.get("region_id", f"q{qno}_{idx}")
            rt = r.get("region_type", "diagram")
            order = r.get("order", idx)
            placement = r.get("placement", "after_stem")
            conf = r.get("crop_confidence", r.get("confidence", 0.8))
            verified = r.get("verified", False)
        out.append(RegionDef(
            qno=qno, page=page, region_id=rid,
            bbox=tuple(b), coord_space=r.get("coordinate_space", "pdf_points"),
            region_type=rt, order=order, placement=placement,
            confidence=conf, requires_review=not verified,
            note=r.get("note", "") if not manual_entries else f"manual:{m.get('bbox_source', 'override')}",
        ))
    return out


def regions_auto(qno, page, pdf_rect, manual_map=None) -> list[RegionDef]:
    """Auto-localize figure region for questions without pre-defined bbox.

    Checks manual bbox overrides first; falls back to heuristic estimate.
    """
    manual_entries = (manual_map or {}).get(qno)
    if manual_entries:
        m = manual_entries[0] if isinstance(manual_entries, list) else manual_entries
        return [RegionDef(
            qno=qno, page=page, region_id=m.get("region_id", f"q{qno}_manual"),
            bbox=tuple(m["bbox"]),
            region_type="diagram", order=0, placement="after_stem",
            confidence=0.75 if m.get("approved") else 0.7,
            requires_review=not m.get("approved", False),
            note=f"manual:{m.get('bbox_source', 'override')}",
        )]
    pw, ph = pdf_rect.width, pdf_rect.height
    margin = pw * 0.15
    top = ph * 0.22
    bot = ph * 0.55
    return [RegionDef(
        qno=qno, page=page, region_id=f"q{qno}_auto",
        bbox=(margin, top, pw - margin, bot),
        region_type="diagram", order=0, placement="after_stem",
        confidence=0.55, requires_review=True,
        note="auto_estimated_no_ocr",
    )]


def compute_snapshot_bbox(qno, page, pdf_rect, content_regions=None):
    """Compute source_snapshot bbox: stem + graphics + options.

    Extends generously downward (to cover options) but only slightly upward
    (to avoid brand header).
    """
    pw, ph = pdf_rect.width, pdf_rect.height
    if content_regions:
        left = min(r.bbox[0] for r in content_regions)
        top = min(r.bbox[1] for r in content_regions) - 5  # minimal upward
        right = max(r.bbox[2] for r in content_regions)
        bottom = max(r.bbox[3] for r in content_regions) + 140  # generous downward
        return ((max(0, left - 10), max(0, top),
                 min(pw, right + 10), min(ph, bottom)),
                "region_extended", 0.7)
    return ((pw * 0.05, ph * 0.05, pw * 0.95, ph * 0.85),
            "page_body", 0.4)


# ── Segment builder ──


def merge_segments(
    existing: list[dict], regions: list[RegionDef], results: list[ImageResult],
) -> list[dict]:
    """Merge new image segments into existing. Idempotent."""
    new_imgs: list[dict] = []
    seen_ids: set[str] = set()
    for reg, r in zip(regions, results):
        if not r.success or not r.url:
            continue
        if reg.region_id in seen_ids:
            continue
        seen_ids.add(reg.region_id)
        dup = False
        for seg in existing:
            if seg.get("region_id") == reg.region_id:
                dup = True
                break
            if seg.get("url") == r.url:
                dup = True
                break
        if dup:
            continue
        new_imgs.append({
            "order": reg.order, "placement": reg.placement,
            "segment": {
                "type": "image", "url": r.url, "display": True,
                "alt": f"图{reg.qno}-{reg.region_id}",
                "region_type": reg.region_type,
                "region_id": reg.region_id,
                "source_page": reg.page,
                "bbox": list(reg.bbox),
                "coordinate_space": reg.coord_space,
                "confidence": reg.confidence,
                "requires_review": reg.requires_review,
            },
        })

    if not new_imgs:
        return existing

    if not existing:
        new_imgs.sort(key=lambda x: x["order"])
        return [x["segment"] for x in new_imgs]

    # Merge: keep existing, insert new at placement points
    # Simple approach: append images after stem (text segment) but before options
    result = []
    added_after_stem = False
    for seg in existing:
        result.append(seg)
        if seg.get("type") == "text" and not added_after_stem:
            for ni in new_imgs:
                if ni["placement"] in ("after_stem", "append"):
                    result.append(ni["segment"])
            added_after_stem = True
    # Append any remaining
    if not added_after_stem:
        for ni in new_imgs:
            result.append(ni["segment"])
    return result


# ── DB helpers ──


async def locate_targets(db, batch_id=None, only_qno=None) -> tuple[list[TargetRecord], list[str]]:
    from app.models.question_import import QuestionImport
    from sqlalchemy import select

    errs = []
    targets = []
    qnos = [only_qno] if only_qno else ALL_IMAGE_QNOS
    for qno in qnos:
        filters = [
            QuestionImport.subject_id == SUBJECT_ID,
            QuestionImport.source_question_no == qno,
        ]
        if batch_id:
            filters.append(QuestionImport.batch_id == batch_id)
        rows = (await db.execute(select(QuestionImport).where(*filters))).scalars().all()
        if len(rows) == 0:
            errs.append(f"qno {qno}: no record")
            continue
        if len(rows) > 1:
            errs.append(f"qno {qno}: {len(rows)} records (ids={[r.id for r in rows]})")
            continue
        r = rows[0]
        targets.append(TargetRecord(
            id=r.id, qno=qno, page=r.source_page_start or qno,
            status=r.status, question_id=r.question_id,
            parsed_content=dict(r.parsed_content or {}),
            batch_id=r.batch_id or "", source_file=r.source_file or "",
        ))
    return targets, errs


# ── Page validation ──


def _validate_content_page(
    pdf_path: str,
    json_page: int,
    db_page: int,
    bbox: list[float] | None,
    *,
    scan_dpi: int = 150,
    min_ink_ratio: float = 0.005,
) -> int:
    """Pick which page has actual diagram content at the bbox region.

    Uses overall ink density to validate content exists.  If both pages
    have content, prefers the DB page since it's more reliable for
    scanned-book PDFs where JSON page numbers may be off by ~5%.
    """
    if not bbox or len(bbox) != 4:
        return db_page

    def _count_ink(pg: int) -> float:
        try:
            import fitz as _fitz
            d = _fitz.open(pdf_path)
            p = d[pg - 1]
            clip = _fitz.Rect(*bbox)
            pix = p.get_pixmap(dpi=scan_dpi, clip=clip, alpha=False)
            d.close()
            samples = pix.samples
            total = len(samples) // 3
            if total == 0:
                return 0.0
            ink = sum(
                1 for i in range(0, len(samples), 3)
                if samples[i] < 248 or samples[i + 1] < 248 or samples[i + 2] < 248
            )
            return ink / total
        except Exception:
            return 0.0

    j_ink = _count_ink(json_page)
    d_ink = _count_ink(db_page)

    # DB page has content → prefer it (more reliable page mapping)
    if d_ink >= min_ink_ratio:
        if j_ink < min_ink_ratio:
            logger.info("  page: DB=%d has content, JSON=%d empty — using DB", db_page, json_page)
        return db_page

    # DB page empty but JSON page has content → use JSON
    if j_ink >= min_ink_ratio:
        logger.info("  page: DB=%d empty, JSON=%d has content — using JSON", db_page, json_page)
        return json_page

    return db_page


# ── Main processing ──


async def process_one(
    target: TargetRecord,
    regions_cfg: dict,
    pdf_path: str,
    storage,
    *, dry_run=False, preview_dir=None,
    ocr_results: dict | None = None,
) -> QuestionReport:
    doc = fitz.open(pdf_path)
    try:
        if target.page < 1 or target.page > len(doc):
            return QuestionReport(qno=target.qno, page=target.page, record_id=target.id,
                                  status=target.status, question_id=target.question_id,
                                  region_errors=[f"page {target.page} out of range"])

        qs = str(target.qno)
        entry = regions_cfg.get(qs) if regions_cfg else None

        # ── Determine effective page: prefer JSON page but validate content ──
        json_page = entry.get("page") if entry and entry.get("bbox") else None
        db_page = target.page
        page_strategy = "default"
        page_conf = 1.0

        if json_page and json_page != db_page:
            # Validate: check which page has actual content at the bbox
            effective_page = _validate_content_page(
                pdf_path, json_page, db_page, entry["bbox"] if entry else None,
            )
            if effective_page != json_page:
                page_strategy = "db_page_has_content"
                page_conf = 0.8
                logger.info("  qno=%d: JSON page %d empty at bbox, using DB page %d (strategy=%s)",
                            target.qno, json_page, db_page, page_strategy)
            elif effective_page != db_page:
                page_strategy = "json_page_has_content"
                page_conf = 0.7
            else:
                page_strategy = "both_pages_match"
                page_conf = 1.0
        elif json_page:
            effective_page = json_page
            if json_page == db_page:
                page_strategy = "match"
                page_conf = 1.0
            else:
                page_strategy = "json_page_only"
                page_conf = 0.6
                logger.info("  qno=%d: no bbox validation — using JSON page %d (DB=%d, strategy=%s)",
                            target.qno, json_page, db_page, page_strategy)
        else:
            effective_page = db_page
            page_strategy = "db_page_no_json"
            page_conf = 0.5

        # Use DB page for rendering context (full page), effective page for regions
        render_page = effective_page
        pdf_page = doc[render_page - 1]
        pr = pdf_page.rect

        manual_map = load_manual_bbox_config()

        if entry and entry.get("bbox"):
            regions = regions_from_manifest(target.qno, effective_page, entry, manual_map=manual_map)
            strategy = "manifest_bbox"
            confidence = entry.get("crop_confidence", entry.get("confidence", 0.8))
        else:
            regions = regions_auto(target.qno, effective_page, pr, manual_map=manual_map)
            strategy = "auto_localized"
            confidence = regions[0].confidence if regions else 0.0

        # ── Step 1: Pre-compute the question_bbox (snapshot) ──
        sbbox, sstrat, sconf = compute_snapshot_bbox(
            target.qno, render_page, pr, regions)

        # ── Step 2: Compute visual_bbox (tight diagram) via foreground analysis ──
        region_results: list[dict] = []
        visual_text_lines: list[dict] = []
        content_quality_issues: list[str] = []
        original_stem = target.parsed_content.get("text", "")
        cleaned_stem = original_stem
        visual_gate_failures: list[str] = []
        header_bottom_pt = pr.y0 + 28.0

        # Load pre-computed OCR for this page, if available
        page_ocr_pt: list[dict] = []
        page_ocr_key = str(effective_page)
        if ocr_results and page_ocr_key in ocr_results:
            ocr_page = ocr_results[page_ocr_key]
            img_size = (ocr_page.get("image_size", {}).get("width", 0),
                        ocr_page.get("image_size", {}).get("height", 0))
            lines_raw = ocr_page.get("lines", [])
            if img_size[0] > 0 and img_size[1] > 0:
                page_ocr_pt = ocr_lines_to_pdf_points(lines_raw, img_size, pr)

        # ── Classify OCR lines and compute diagram analysis zone ──
        stem_bottom_pt: float | None = None
        first_opt_top: float | None = None
        diagram_zone_top: float | None = None
        diagram_zone_bot: float | None = None

        if page_ocr_pt:
            zones = classify_ocr_lines(page_ocr_pt, pr.height)
            opt_lines = zones.get(_ZONE_OPTION, [])

            stem_bottom_pt = compute_stem_bottom_pt(page_ocr_pt, pr.height)
            first_opt_top = detect_first_option_pt(page_ocr_pt) if opt_lines else None

            if stem_bottom_pt is not None:
                diagram_zone_top = stem_bottom_pt + _STEM_BOTTOM_MARGIN_PT
            if first_opt_top is not None:
                diagram_zone_bot = first_opt_top - _OPTION_TOP_MARGIN_PT

            logger.debug(
                "  qno=%d: stem_bottom=%.1f first_opt_top=%s diagram_zone=[%s, %s]",
                target.qno,
                stem_bottom_pt or -1,
                f"{first_opt_top:.1f}" if first_opt_top is not None else "None",
                f"{diagram_zone_top:.1f}" if diagram_zone_top is not None else "None",
                f"{diagram_zone_bot:.1f}" if diagram_zone_bot is not None else "None",
            )

        # diagnostic: store pre-refine info
        diag_visual_before_refine = None

        for reg in regions:
            # ── Step 2a: Refine bbox to tight diagram area ──
            # For manual_override entries, use the configured bbox directly (skip foreground refinement)
            if 'manual_override' in reg.note:
                visual_bbox_pt = reg.bbox
            else:
                visual_bbox_pt = compute_visual_bbox_from_foreground(
                    pdf_path, render_page, reg.bbox, pr,
                    padding_pt=8.0, scan_dpi=CONTENT_FOREGROUND_SCAN_DPI,
                    ocr_lines_pt=page_ocr_pt or None,
                    analysis_range_pt=(diagram_zone_top, diagram_zone_bot) if (diagram_zone_top is not None or diagram_zone_bot is not None) else None,
                )
            diag_visual_before_refine = visual_bbox_pt

            # ── Step 2b: Ensure visual_bbox stays above options ──
            if first_opt_top is not None:
                visual_bbox_pt = refine_visual_bbox_for_options(
                    visual_bbox_pt, first_opt_top, reg.bbox, min_gap_pt=4.0,
                )

            # ── Step 2c: Add safe padding to visual_bbox ──
            padded_visual_pt = _padded_bbox(visual_bbox_pt, VISUAL_PADDING_PT)
            # Clamp back to region bbox
            padded_visual_pt = (
                max(reg.bbox[0], padded_visual_pt[0]),
                max(reg.bbox[1], padded_visual_pt[1]),
                min(reg.bbox[2], padded_visual_pt[2]),
                min(reg.bbox[3], padded_visual_pt[3]),
            )
            # Exclude brand header zone (defensive — banner can extend to ~26pt)
            if padded_visual_pt[1] < header_bottom_pt:
                padded_visual_pt = (padded_visual_pt[0], header_bottom_pt,
                                    padded_visual_pt[2], padded_visual_pt[3])

            # Step 2c.5: Ensure we have minimum content size
            if (padded_visual_pt[2] - padded_visual_pt[0] < 30 or
                padded_visual_pt[3] - padded_visual_pt[1] < 30):
                # Too small — expand to region bbox with header exclusion
                padded_visual_pt = (reg.bbox[0], max(reg.bbox[1], header_bottom_pt),
                                    reg.bbox[2], reg.bbox[3])

            # ── Step 2d: OCR overlap analysis & stem cleanup ──
            if page_ocr_pt:
                viz_text, kept_text = analyze_ocr_overlap(
                    page_ocr_pt, padded_visual_pt,
                    threshold=OVERLAP_THRESHOLD,
                )
                visual_text_lines.extend(viz_text)
                if viz_text:
                    cleaned_stem = clean_stem_from_visual_text(
                        original_stem, kept_text, viz_text,
                    )

            # ── Step 3: Render content image (tight visual bbox) ──
            ir = render_clip(
                pdf_path, render_page, padded_visual_pt,
                dpi=220, padding_pt=0.0,
                render_bbox_as_is=True,  # use padded_visual_pt as-is (header already excluded)
            )
            sk = content_storage_key(
                SOURCE_FILE, render_page, target.qno, padded_visual_pt,
                kind="content", crop_version=CROP_VERSION,
            )
            ir.storage_key = sk

            # ── Hard visual quality gate (before accepting render) ──
            if ir.success and ir.png:
                gate_fails = check_visual_gate(
                    padded_visual_pt, pr,
                    stem_bottom_pt=stem_bottom_pt,
                    first_option_top_pt=first_opt_top,
                    header_bottom_pt=header_bottom_pt,
                )
                visual_gate_failures.extend(gate_fails)

                # Also check header pollution in rendered pixels
                if check_header_pollution(ir.png):
                    gate_fails.append("header_pollution_detected_in_pixels")

                if gate_fails:
                    ir.success = False
                    ir.error = "; ".join(gate_fails)
                    ir.requires_review = True
                    logger.warning(
                        "  qno=%d: VISUAL GATE FAILED: %s", target.qno, gate_fails
                    )

            # Quality checks (pixel/size level)
            if ir.success:
                if ir.width < CONTENT_MIN_W or ir.height < CONTENT_MIN_H:
                    ir.success = False; ir.error = f"too small {ir.width}x{ir.height}"
                elif ir.file_size < CONTENT_MIN_BYTES:
                    ir.success = False; ir.error = f"tiny file {ir.file_size}B"
                elif ir.blank_ratio > CONTENT_MAX_BLANK_RATIO:
                    ir.success = False; ir.error = f"blank {ir.blank_ratio:.3f}"
                elif ir.nonwhite_ratio < CONTENT_MIN_NONWHITE_RATIO:
                    ir.success = False; ir.error = f"uniform {ir.nonwhite_ratio:.3f}"

            # ── Visual completeness gate ──
            if ir.success and ir.png:
                completeness_issues = check_visual_completeness(
                    ir.png, padded_visual_pt,
                    ocr_visual_texts=visual_text_lines if visual_text_lines else None,
                )
                content_quality_issues.extend(completeness_issues)
                for ci in completeness_issues:
                    ir.requires_review = True

            # ── Quality gate for content image ──
            if ir.success and ir.png:
                issues = check_content_image_quality(
                    ir.png,
                    ocr_texts=[l["text"] for l in page_ocr_pt] if page_ocr_pt else None,
                )
                content_quality_issues.extend(issues)
                for iss in issues:
                    if iss == "header_pollution":
                        ir.success = False
                        ir.error = f"quality:{iss}"
                        ir.requires_review = True

            # ── Storage (dry-run or real) ──
            if dry_run and preview_dir:
                os.makedirs(preview_dir, exist_ok=True)
                lp = os.path.join(preview_dir, sk.replace("/", "_"))
                if ir.png:
                    with open(lp, "wb") as f:
                        f.write(ir.png)
                ir.url = f"file://{lp}"
            elif not dry_run:
                if ir.png:
                    ir.url = await storage.upload(sk, ir.png)

            rreq = reg.requires_review or ir.requires_review
            if ir.has_header:
                rreq = True
            if content_quality_issues:
                rreq = True
            if visual_gate_failures:
                rreq = True
            asset_hash = hashlib.sha256(ir.png).hexdigest() if ir.png else ""
            region_results.append({
                "region_id": reg.region_id,
                "original_bbox": list(reg.bbox),
                "visual_bbox": list(padded_visual_pt),
                "visual_bbox_before_pad": list(diag_visual_before_refine) if diag_visual_before_refine else None,
                "foreground_bbox": list(visual_bbox_pt),
                "success": ir.success,
                "width": ir.width, "height": ir.height,
                "file_size": ir.file_size,
                "blank_ratio": round(ir.blank_ratio, 4),
                "url": ir.url, "error": ir.error,
                "requires_review": rreq,
                "crop_version": CROP_VERSION,
                "visual_gate_failures": list(visual_gate_failures),
                "asset_hash": asset_hash,
            })

        # ── Step 4: Render source snapshot (question_bbox via render_clip) ──
        sr = render_clip(pdf_path, render_page, sbbox,
                         dpi=220, padding_pt=8.0)
        if sr.success:
            if sr.width < SNAPSHOT_MIN_W or sr.height < SNAPSHOT_MIN_H:
                sr.success = False; sr.error = f"snap too small {sr.width}x{sr.height}"
            elif sr.file_size < SNAPSHOT_MIN_BYTES:
                sr.success = False; sr.error = f"snap tiny {sr.file_size}B"
        ssk = content_storage_key(
            SOURCE_FILE, render_page, target.qno, sbbox,
            kind="snapshot", crop_version=CROP_VERSION,
        )
        if dry_run and preview_dir:
            lp = os.path.join(preview_dir, ssk.replace("/", "_"))
            if sr.png:
                with open(lp, "wb") as f:
                    f.write(sr.png)
            snap_url = f"file://{lp}"
        elif not dry_run:
            if sr.png:
                snap_url = await storage.upload(ssk, sr.png)
        else:
            snap_url = ""

        snap_dict = {
            "bbox": list(sbbox), "strategy": sstrat, "confidence": round(sconf, 2),
            "success": sr.success, "width": sr.width, "height": sr.height,
            "file_size": sr.file_size, "url": snap_url, "error": sr.error,
            "blank_ratio": round(sr.blank_ratio, 4),
            "crop_version": CROP_VERSION,
        }

        warnings = [r["error"] for r in region_results if r["error"]]
        if sr.error:
            warnings.append(f"snapshot: {sr.error}")
        all_ok = all(r["success"] for r in region_results)
        need_review = any(r.get("requires_review") for r in region_results)
        if confidence < CONF_AUTO:
            need_review = True
        if content_quality_issues:
            need_review = True
        if visual_gate_failures:
            need_review = True

        content_preview = (cleaned_stem or original_stem)[:100].strip()
        bbox_source = "manifest_json"
        if any("manual" in r.get("region_id", "") for r in region_results):
            bbox_source = "manual_bbox_config"
        elif strategy == "auto_localized":
            bbox_source = "auto_localized"

        return QuestionReport(
            qno=target.qno, page=target.page, record_id=target.id,
            status=target.status, question_id=target.question_id,
            regions=region_results, region_errors=[],
            snapshot_result=snap_dict, strategy=strategy,
            confidence=confidence, requires_review=need_review or not all_ok,
            warnings=warnings,
            # Identifier fields
            question_import_id=target.id,
            source_question_no=target.qno,
            batch_id=target.batch_id,
            is_published=target.question_id is not None,
            # Page tracking
            db_source_page=db_page,
            configured_pdf_page=json_page,
            resolved_pdf_page=effective_page,
            page_resolution_strategy=page_strategy,
            page_confidence=page_conf,
            # Bbox source
            bbox_source=bbox_source,
            # Content preview
            content_preview=content_preview,
            # Dual-bbox / stem-cleanup diagnostics
            original_stem=original_stem,
            cleaned_stem=cleaned_stem,
            excluded_visual_text=visual_text_lines,
            visual_bbox=list(padded_visual_pt) if region_results else None,
            question_bbox=list(sbbox),
            content_quality_issues=content_quality_issues,
            crop_version=CROP_VERSION,
        )
    finally:
        doc.close()


async def apply_updates(
    db, targets, reports, storage, *, dry_run=False,
) -> tuple[list[str], int, list[str]]:
    from app.models.question_import import QuestionImport
    from app.models.question import Question
    from sqlalchemy import select

    errs = []
    imp_updated = 0
    q_updated = []
    if dry_run:
        return errs, 0, []

    now_ts = datetime.utcnow().isoformat()

    async with db.begin():
        for target, rep in zip(targets, reports):
            qi_row = (await db.execute(
                select(QuestionImport).where(QuestionImport.id == target.id)
            )).scalar_one_or_none()
            if not qi_row:
                errs.append(f"qno {target.qno}: not found in DB")
                continue

            pc = dict(target.parsed_content)

            # ── Use cleaned stem text if available ──
            clean_text = ""
            if rep.cleaned_stem and rep.cleaned_stem != rep.original_stem:
                clean_text = rep.cleaned_stem
                pc["text"] = clean_text
            else:
                clean_text = pc.get("text", "")

            # ── Build segments with proper replacement ──
            # Strategy: keep non-image segments, replace existing content_image
            # segments (matched by region_id or semantic_role), then append new ones.
            old_image_region_ids: set[str] = set()
            kept_non_image: list[dict] = []

            old_segs = pc.get("segments", [])
            for seg in old_segs:
                stype = seg.get("type", "")
                if stype == "image":
                    rid = seg.get("region_id", "")
                    role = seg.get("semantic_role", "")
                    if rid:
                        old_image_region_ids.add(rid)
                    # Replace old image segments: content_image role OR unlabeled old images
                    if role == "content_image":
                        continue
                    if role == "":
                        continue  # old-style image without role
                    # Other explicit image roles: keep
                    kept_non_image.append(seg)
                elif stype == "text":
                    pass  # handled below
                else:
                    kept_non_image.append(seg)

            # Text segment (first)
            new_segments: list[dict] = []
            new_segments.append({
                "type": "text", "text": clean_text,
            })
            new_segments.extend(kept_non_image)

            # Image segments from region results
            new_image_count = 0
            for rr in rep.regions:
                if not (rr.get("success") and rr.get("url")):
                    continue
                region_id = rr.get("region_id", f"q{target.qno}_{new_image_count}")
                bbox_source = rep.bbox_source
                asset_hash = rr.get("asset_hash", "")

                new_segments.append({
                    "type": "image", "url": rr["url"],
                    "display": True,
                    "alt": f"图{target.qno}-{region_id}",
                    "region_type": rr.get("region_id", "diagram"),
                    "region_id": region_id,
                    "semantic_role": "content_image",
                    "source_page": target.page,
                    "bbox": rr.get("visual_bbox", rr.get("original_bbox", [])),
                    "original_bbox": rr.get("original_bbox", []),
                    "coordinate_space": "pdf_points",
                    "crop_version": rr.get("crop_version", CROP_VERSION),
                    "bbox_source": bbox_source,
                    "asset_hash": asset_hash,
                    "confidence": rep.confidence,
                    "requires_review": rr.get("requires_review", False),
                    "generated_at": now_ts,
                })
                new_image_count += 1

            if new_segments:
                pc["segments"] = new_segments
                pc["render_mode"] = "segments"

            # ── Source snapshot (visual_bbox + question_bbox) ──
            sr = rep.snapshot_result
            if sr and sr.get("success") and sr.get("url"):
                pc["source_snapshot_url"] = sr["url"]
                pc["source_snapshot_full_page"] = False
                pc["source_snapshot_page"] = target.page
                pc["source_snapshot_bbox"] = sr["bbox"]
                pc["source_snapshot_coordinate_space"] = "pdf_points"
                pc["source_snapshot_strategy"] = sr["strategy"]
                pc["source_snapshot_coverage"] = sr["confidence"]

            # Store visual_bbox separately in metadata
            if rep.visual_bbox:
                pc["content_visual_bbox"] = rep.visual_bbox
                pc["content_visual_coordinate_space"] = "pdf_points"
                pc["content_crop_version"] = rep.crop_version
            if rep.question_bbox:
                pc["question_bbox"] = rep.question_bbox
                pc["question_bbox_coordinate_space"] = "pdf_points"

            qi_row.parsed_content = pc
            imp_updated += 1

            # ── Published Question sync ──
            if target.question_id:
                q_row = (await db.execute(
                    select(Question).where(Question.id == target.question_id)
                )).scalar_one_or_none()
                if q_row:
                    qc = dict(q_row.content or {})
                    if new_segments:
                        qc["segments"] = new_segments
                        qc["render_mode"] = "segments"
                        qc["text"] = clean_text
                    q_row.content = qc
                    urls = [s["url"] for s in new_segments if s.get("type") == "image"]
                    if urls:
                        q_row.image_url = urls
                    q_updated.append(f"Q(id={target.question_id}, qno={target.qno})")

            # ── Set image_url from first content_image segment (even if unpublished) ──
            if new_image_count > 0 and not target.question_id:
                first_img_url = new_segments[-new_image_count]["url"]
                qi_row.source_image_name = first_img_url

    return errs, imp_updated, q_updated


# ── HTML report ──


def gen_html(reports: list[QuestionReport], path: str) -> str:
    parts = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'>",
        "<title>题目补图审核报告</title><style>",
        "body{font-family:sans-serif;margin:20px;background:#f5f5f5}",
        ".card{background:#fff;border-radius:8px;padding:16px;margin:16px 0;box-shadow:0 2px 4px rgba(0,0,0,.1)}",
        "h2{color:#333} .badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:bold}",
        ".ok{background:#d4edda;color:#155724} .fail{background:#f8d7da;color:#721c24}",
        ".review{background:#fff3cd;color:#856404}",
        "img{max-width:100%;border:1px solid #ddd;margin:4px}",
        "table{border-collapse:collapse;width:100%} td,th{border:1px solid #ddd;padding:8px}",
        ".meta{font-size:13px;color:#666} .warn{background:#fff3cd;color:#856404;padding:4px 8px}",
        "</style></head><body>",
        "<h1>题目补图审核报告</h1>",
        f"<p>{datetime.now().isoformat()} | {len(reports)} 题 | "
        f"需审核: {sum(1 for r in reports if r.requires_review)}</p>",
    ]
    for r in reports:
        badge = "<span class='badge ok'>自动</span>"
        if r.requires_review:
            badge = "<span class='badge review'>需审核</span>"
        if r.region_errors:
            badge = "<span class='badge fail'>失败</span>"
        parts.append(f"<div class='card'><h2>题{r.qno} (P{r.page}) {badge}</h2>")
        parts.append(f"<p class='meta'>策略:{r.strategy} 置信度:{r.confidence:.2f} "
                     f"记录ID:{r.record_id} QuestionID:{r.question_id or 'N/A'} "
                     f"crop:{r.crop_version}</p>")

        # Dual-bbox info
        if r.visual_bbox:
            parts.append(f"<p><b>Visual bbox:</b> {r.visual_bbox} | "
                         f"<b>Question bbox:</b> {r.question_bbox}</p>")

        # Left: content image | Right: source snapshot
        parts.append("<div style='display:flex;gap:16px'>")

        # Content image section
        parts.append("<div style='flex:1'>")
        parts.append("<h3>Content Image (visual_bbox)</h3>")
        if r.regions:
            parts.append("<table><tr><th>预览</th><th>Visual Bbox</th><th>尺寸</th><th>状态</th></tr>")
            for rg in r.regions:
                st = "✅" if rg["success"] else "❌"
                prev = f"<img src='{rg['url']}' height='120'>" if rg.get("url") else "-"
                vb = rg.get("visual_bbox", rg.get("original_bbox", []))
                parts.append(f"<tr><td>{prev}</td><td>{vb}</td>"
                             f"<td>{rg['width']}x{rg['height']}</td>"
                             f"<td>{st}{' 🔍' if rg.get('requires_review') else ''}</td></tr>")
            parts.append("</table>")
        if r.content_quality_issues:
            parts.append(f"<div class='warn'>质量问题: {', '.join(r.content_quality_issues)}</div>")
        parts.append("</div>")

        # Snapshot section
        parts.append("<div style='flex:1'>")
        sr = r.snapshot_result
        if sr:
            parts.append(f"<h3>Source Snapshot (question_bbox)</h3><p class='meta'>"
                         f"bbox:{sr.get('bbox')} 策略:{sr.get('strategy')} "
                         f"置信度:{sr.get('confidence')} 尺寸:{sr.get('width')}x{sr.get('height')}</p>")
            if sr.get("url"):
                parts.append(f"<img src='{sr['url']}' height='200'>")
        parts.append("</div>")

        parts.append("</div>")

        # Stem diagnostics
        if r.original_stem or r.cleaned_stem:
            parts.append("<div style='margin-top:8px;background:#f8f9fa;padding:8px;border-radius:4px'>")
            parts.append(f"<p><b>原始题干:</b> <code>{r.original_stem[:200]}</code></p>")
            if r.cleaned_stem and r.cleaned_stem != r.original_stem:
                parts.append(f"<p><b>清理后题干:</b> <code>{r.cleaned_stem[:200]}</code></p>")
            if r.excluded_visual_text:
                parts.append(f"<p><b>排除的 visual_text ({len(r.excluded_visual_text)}):</b></p>")
                parts.append("<ul>")
                for vt in r.excluded_visual_text[:20]:
                    parts.append(f"<li><code>{vt['text']}</code> "
                                 f"overlap={vt.get('overlap_ratio',0):.3f} "
                                 f"bbox={vt.get('bbox_pt', [])}</li>")
                if len(r.excluded_visual_text) > 20:
                    parts.append(f"<li>... 共{len(r.excluded_visual_text)}行</li>")
                parts.append("</ul>")
            parts.append("</div>")

        # Visual gate failures
        for rg in r.regions:
            vgf = rg.get("visual_gate_failures", [])
            if vgf:
                parts.append(f"<div class='warn'>视觉门禁失败: {'; '.join(vgf)}</div>")

        # ── Approval checklist ──
        parts.append("<div style='margin-top:8px;padding:8px;background:#e8f5e9;border-radius:4px'>")
        parts.append("<b>审核清单 (三项均通过后才可 apply):</b><br>")
        stem_ok = "OK" if (r.cleaned_stem and r.cleaned_stem != r.original_stem) or r.original_stem else "?"
        img_ok = "OK" if any(rg["success"] for rg in r.regions) else "FAIL"
        snap_ok = "OK" if r.snapshot_result and r.snapshot_result.get("success") else "FAIL"
        parts.append(f" 清理题干: {stem_ok} | Content Image: {img_ok} | Source Snapshot: {snap_ok}")
        parts.append("</div>")

        for w in r.warnings:
            parts.append(f"<div class='warn'>WARN {w}</div>")
        parts.append("</div>")
    parts.append("</body></html>")
    html = "\n".join(parts)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        f.write(html)
    logger.info("HTML report: %s", path)
    return path


# ── CLI ──


def parse_args():
    p = argparse.ArgumentParser(description="Backfill question images from PDF")
    p.add_argument("--db", required=True, help="DB URL e.g. sqlite+aiosqlite:///./postgraduate.db")
    p.add_argument("--pdf", required=True, help="Path to source PDF")
    p.add_argument("--batch-id", help="Filter by batch_id")
    p.add_argument("--only-question", type=int, help="Process single question")
    p.add_argument("--dry-run", action="store_true", default=True, help="Preview only (default)")
    p.add_argument("--apply", action="store_true", help="Apply changes (implies --no-dry-run)")
    p.add_argument("--report", default="/tmp/backfill-review.html", help="Output report path")
    p.add_argument("--preview-dir", default="/tmp/backfill-preview", help="Dry-run preview dir")
    p.add_argument("--approval-file", help="Path to approval.json for --apply filtering")
    p.add_argument("--ocr-results", default=OCR_RESULTS_PATH,
                   help="Pre-computed OCR results JSON for overlap analysis")
    return p.parse_args()


async def main():
    args = parse_args()
    if args.apply:
        args.dry_run = False

    if not os.path.isfile(args.pdf):
        logger.error("PDF not found: %s", args.pdf)
        sys.exit(1)

    # ── Validate regions config ──
    regions_cfg = load_regions()
    if regions_cfg:
        doc = fitz.open(args.pdf)
        total_pg = len(doc)
        doc.close()
        errs = []
        seen = set()
        for qs, entry in regions_cfg.items():
            qno = int(qs) if qs.isdigit() else 0
            if qno and qno not in ALL_IMAGE_QNOS:
                errs.append(f"qno {qno} not in image-dependent list")
            pg = entry.get("page", 0)
            if pg < 1 or pg > total_pg:
                errs.append(f"qno {qno}: page {pg} out of range")
            b = entry.get("bbox")
            if b:
                if len(b) != 4:
                    errs.append(f"qno {qno}: bbox len != 4")
                elif b[2] <= b[0] or b[3] <= b[1]:
                    errs.append(f"qno {qno}: bbox invalid {b}")
            rid = entry.get("region_id", f"q{qno}")
            if rid in seen:
                errs.append(f"duplicate region_id {rid}")
            seen.add(rid)
        if errs:
            logger.error("Config validation FAILED:")
            for e in errs:
                logger.error("  - %s", e)
            sys.exit(1)
        logger.info("Config OK: %d entries, %d with bbox, %d auto",
                    len(regions_cfg),
                    sum(1 for v in regions_cfg.values() if v.get("bbox")),
                    sum(1 for v in regions_cfg.values() if not v.get("bbox")))

    # ── Honour --db CLI argument ──
    os.environ["DATABASE_URL"] = args.db

    # ── Locate DB records ──
    from app.core.database import async_session

    async with async_session() as db:
        targets, loc_errs = await locate_targets(
            db, batch_id=args.batch_id, only_qno=args.only_question)
        if loc_errs:
            for e in loc_errs:
                logger.error("Locate error: %s", e)
        if not args.only_question and len(targets) != len(ALL_IMAGE_QNOS):
            logger.warning("Found %d/%d targets", len(targets), len(ALL_IMAGE_QNOS))
        if not targets:
            logger.error("No targets, abort")
            sys.exit(1)
        # Backup
        backup = []
        from app.models.question_import import QuestionImport
        from app.models.question import Question
        from sqlalchemy import select as _sel
        for t in targets:
            entry = {"id": t.id, "qno": t.qno, "status": t.status,
                     "question_id": t.question_id,
                     "parsed_content": dict(t.parsed_content)}
            if t.question_id:
                qr = (await db.execute(_sel(Question).where(Question.id == t.question_id))
                      ).scalar_one_or_none()
                if qr:
                    entry["q_content"] = dict(qr.content or {})
                    entry["q_image_url"] = qr.image_url
            backup.append(entry)
        pub = sum(1 for b in backup if b.get("question_id"))
        logger.info("Backup: %d targets (%d published)", len(backup), pub)

    # ── Load pre-computed OCR results ──
    ocr_data = load_precomputed_ocr(args.ocr_results)
    if ocr_data:
        logger.info("Loaded OCR results for pages: %s", sorted(ocr_data.keys()))

    # ── Process ──
    from app.services.storage_backend import get_question_assets_storage
    storage = get_question_assets_storage()
    reports = []
    for t in targets:
        logger.info("Processing qno=%d page=%d id=%d ...", t.qno, t.page, t.id)
        rep = await process_one(t, regions_cfg, args.pdf, storage,
                                dry_run=args.dry_run, preview_dir=args.preview_dir,
                                ocr_results=ocr_data)
        reports.append(rep)
        st = "✅" if not rep.requires_review else "🔍"
        stem_info = ""
        if rep.cleaned_stem and rep.cleaned_stem != rep.original_stem:
            stem_info = f" stem_cleaned(excluded={len(rep.excluded_visual_text)})"
        logger.info("  %s qno=%-4d %-20s conf=%.2f regions=%d%s%s",
                    st, rep.qno, rep.strategy, rep.confidence, len(rep.regions),
                    f" snap={'✅' if rep.snapshot_result and rep.snapshot_result.get('success') else '❌'}",
                    stem_info)

    # ── Persistent output directory ──
    run_id = datetime.now().strftime("run_%Y%m%d_%H%M%S")
    out_dir = os.path.join(
        os.path.dirname(__file__), "..",
        f"artifacts/backfill/ds_sc/{CROP_VERSION}/{run_id}",
    )
    os.makedirs(out_dir, exist_ok=True)
    logger.info("Output directory: %s", out_dir)

    # ── Save backup ──
    backup_path = os.path.join(out_dir, "backup.json")
    with open(backup_path, "w") as f:
        json.dump(backup, f, ensure_ascii=False, indent=2, default=str)
    logger.info("Backup saved: %s", backup_path)

    # ── Content images and snapshots ──
    content_dir = os.path.join(out_dir, "content-images")
    snapshot_dir = os.path.join(out_dir, "source-snapshots")
    overlay_dir = os.path.join(out_dir, "overlay")
    for d in (content_dir, snapshot_dir, overlay_dir):
        os.makedirs(d, exist_ok=True)

    # Copy preview images to persistent dirs
    for rep in reports:
        for rg in rep.regions:
            url = rg.get("url", "")
            if url and url.startswith("file://"):
                src = url[7:]
                if os.path.isfile(src):
                    dst = os.path.join(content_dir, os.path.basename(src))
                    shutil.copy2(src, dst)
                    rg["url"] = f"file://{dst}"
        sr = rep.snapshot_result
        if sr:
            url = sr.get("url", "")
            if url and url.startswith("file://"):
                src = url[7:]
                if os.path.isfile(src):
                    dst = os.path.join(snapshot_dir, os.path.basename(src))
                    shutil.copy2(src, dst)
                    sr["url"] = f"file://{dst}"

    # ── HTML report ──
    html_path = os.path.join(out_dir, "review.html")
    gen_html(reports, html_path)
    logger.info("HTML report: %s", html_path)

    # ── Generate approval.json template ──
    approval_entries = []
    for rep in reports:
        stem_approved = False
        content_approved = False
        snapshot_approved = False
        # Auto-approve only if all gates pass and conf >= CONF_AUTO
        if not rep.requires_review and rep.confidence >= CONF_AUTO:
            stem_approved = True
            if any(rg["success"] for rg in rep.regions):
                content_approved = True
            if rep.snapshot_result and rep.snapshot_result.get("success"):
                snapshot_approved = True

        approval_entries.append({
            "question_import_id": rep.question_import_id,
            "source_question_no": rep.source_question_no,
            "resolved_pdf_page": rep.resolved_pdf_page,
            "batch_id": rep.batch_id,
            "is_published": rep.is_published,
            "bbox_source": rep.bbox_source,
            "page_resolution_strategy": rep.page_resolution_strategy,
            "page_confidence": rep.page_confidence,
            "approved": {
                "cleaned_stem": stem_approved,
                "content_image": content_approved,
                "source_snapshot": snapshot_approved,
            },
            "all_approved": stem_approved and content_approved and snapshot_approved,
            "confidence": rep.confidence,
            "requires_review": rep.requires_review,
            "warnings": rep.warnings,
        })
    approval_path = os.path.join(out_dir, "approval.json")
    with open(approval_path, "w") as f:
        json.dump({
            "run_id": run_id,
            "crop_version": CROP_VERSION,
            "created": datetime.now().isoformat(),
            "pdf_sha256": "0ede22748f2a00c3f36ef67c792d0de9ce004c3d046260e83835638af45893fb",
            "instructions": "Set each question's three approval items to true after manual review. "
                           "Then pass --approval <path> to --apply. "
                           "Unapproved records are skipped.",
            "entries": approval_entries,
        }, f, ensure_ascii=False, indent=2)
    logger.info("Approval template: %s", approval_path)

    # ── Apply ──
    if args.apply and not args.dry_run:
        # Check for approval file
        approval_data = None
        approval_path_arg = getattr(args, "approval_file", None) or os.path.join(out_dir, "approval.json")
        if os.path.isfile(approval_path_arg):
            with open(approval_path_arg) as f:
                approval_data = json.load(f)
            logger.info("Loaded approval from: %s", approval_path_arg)
        elif getattr(args, "approval_file", None):
            logger.error("Approval file not found: %s", args.approval_file)
            logger.error("Generate one via dry-run first, then edit and pass back.")
            sys.exit(1)

        from app.core.database import async_session
        async with async_session() as db:
            approved_qnos = set()
            if approval_data:
                for ae in approval_data.get("entries", []):
                    if ae.get("all_approved"):
                        approved_qnos.add(ae["source_question_no"])

            # Filter targets to only approved
            apply_targets = []
            apply_reports = []
            for t, rep in zip(targets, reports):
                if not approval_data:
                    # No approval file → require manual approval
                    if rep.requires_review:
                        logger.warning("  SKIP qno=%d (no approval, requires_review=True)", rep.qno)
                        continue
                elif rep.source_question_no not in approved_qnos:
                    logger.info("  SKIP qno=%d (not approved in approval.json)", rep.qno)
                    continue
                apply_targets.append(t)
                apply_reports.append(rep)

            if not apply_targets:
                logger.warning("No approved targets to apply. Generate approval.json and approve entries first.")
            else:
                errs, imp_upd, q_upd = await apply_updates(
                    db, apply_targets, apply_reports, storage, dry_run=False)
                if errs:
                    for e in errs:
                        logger.error("Apply error: %s", e)
                else:
                    await db.commit()
                    logger.info("Applied: %d imports, %d questions", imp_upd, len(q_upd))
                    for qu in q_upd:
                        logger.info("  - %s", qu)

                # ── Apply report ──
                apply_report_path = os.path.join(out_dir, "apply-report.json")
                with open(apply_report_path, "w") as f:
                    json.dump({
                        "run_id": run_id,
                        "applied_at": datetime.now().isoformat(),
                        "total_targets": len(apply_targets),
                        "imports_updated": imp_upd,
                        "questions_updated": len(q_upd),
                        "errors": errs,
                    }, f, ensure_ascii=False, indent=2)
                logger.info("Apply report: %s", apply_report_path)
    else:
        logger.info("Dry-run. Use --apply to execute.")
        logger.info("Review the approval template at: %s", approval_path)
        logger.info("After manual review: python scripts/backfill_question_images.py --db <db> --pdf <pdf> --apply --report %s/review.html --preview-dir %s --ocr-results <ocr> --approval-file %s",
                    out_dir, out_dir, approval_path)

    # ── Summary ──
    auto = sum(1 for r in reports if not r.requires_review and not r.region_errors)
    review = sum(1 for r in reports if r.requires_review)
    fail = sum(1 for r in reports if r.region_errors)
    gate_fail = sum(1 for r in reports if any(
        rg.get("visual_gate_failures") for rg in r.regions
    ))
    logger.info("=" * 50)
    logger.info("SUMMARY: total=%d auto=%d review=%d failed=%d gate_fail=%d stem_cleaned=%d",
                len(reports), auto, review, fail, gate_fail,
                sum(1 for r in reports if r.cleaned_stem and r.cleaned_stem != r.original_stem))
    if review:
        logger.info("Needs review:")
        for r in reports:
            if r.requires_review:
                vgf = ""
                for rg in r.regions:
                    f = rg.get("visual_gate_failures", [])
                    if f:
                        vgf = f" gate=[{' '.join(f)}]"
                logger.info("  - qno=%d %s conf=%.2f%s%s", r.qno, r.strategy, r.confidence,
                           f" issues={r.content_quality_issues}" if r.content_quality_issues else "",
                           vgf)

    # Output JSON summary
    summary_path = os.path.join(out_dir, "review.json")
    with open(summary_path, "w") as f:
        json.dump([{
            "qno": r.qno,
            "question_import_id": r.question_import_id,
            "source_question_no": r.source_question_no,
            "batch_id": r.batch_id,
            "is_published": r.is_published,
            "db_source_page": r.db_source_page,
            "configured_pdf_page": r.configured_pdf_page,
            "resolved_pdf_page": r.resolved_pdf_page,
            "page_resolution_strategy": r.page_resolution_strategy,
            "page_confidence": r.page_confidence,
            "bbox_source": r.bbox_source,
            "content_preview": r.content_preview,
            "page": r.page, "record_id": r.record_id,
            "strategy": r.strategy, "confidence": r.confidence,
            "requires_review": r.requires_review,
            "num_regions": len(r.regions),
            "snapshot_ok": r.snapshot_result.get("success") if r.snapshot_result else False,
            "warnings": r.warnings,
            "stem_cleaned": r.cleaned_stem != r.original_stem if r.cleaned_stem else False,
            "num_excluded_visual_text": len(r.excluded_visual_text),
            "visual_bbox": r.visual_bbox,
            "question_bbox": r.question_bbox,
            "content_quality_issues": r.content_quality_issues,
            "crop_version": r.crop_version,
            "visual_gate_failures": [
                rg.get("visual_gate_failures", [])
                for rg in r.regions if rg.get("visual_gate_failures")
            ],
        } for r in reports], f, ensure_ascii=False, indent=2)
    logger.info("JSON summary: %s", summary_path)


if __name__ == "__main__":
    asyncio.run(main())
