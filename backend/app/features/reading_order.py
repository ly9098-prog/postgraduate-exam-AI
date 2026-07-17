"""Reading Order Resolver — rule-based column detection and region ordering.

Relies only on PageIR geometry (bbox), not on OCR text content or array position.
Designed to be pure-functional, deterministic, and testable with shuffled input.

Design:
1. Classify page layout as single-column, double-column, or multi-column
   based on region x-distribution and page width.
2. Detect cross-column titles (regions spanning >70% of page width).
3. Order within each column by y-coordinate (top-to-bottom).
4. Multi-column: order left-to-right, each column top-to-bottom.
5. Headers, footers, and watermarks are excluded from main reading order
   and placed in separate sequences.
6. Figures, tables, formulas, and code regions are anchored to their
   spatial position in the reading flow.
7. Risk flags are generated for ambiguous, overlapping, isolated regions
   and low-confidence assignments.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

from app.core.document_ir import BBox, PageIR, RegionIR, RegionType


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ReadingOrderError(Exception):
    """Raised when reading order resolution fails catastrophically."""


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReadingOrderEdge:
    """Directed edge between two regions in reading order.

    ``source_region_id`` → ``target_region_id`` with a confidence score
    and human-readable reason.
    """
    source_region_id: str
    target_region_id: str
    confidence: float
    reason: str


@dataclass
class ReadingOrderResult:
    """Result of resolving a single page's reading order."""
    ordered_region_ids: list[str]
    edges: list[ReadingOrderEdge]
    confidence: float              # 0.0–1.0 overall confidence
    strategy: str                  # "single_column" | "double_column" | "multi_column"
    risk_flags: list[str]          # e.g. ["column_count_ambiguous", "overlapping_regions"]
    column_assignments: dict[str, int] = field(default_factory=dict)  # region_id → column index

    @property
    def has_risks(self) -> bool:
        return len(self.risk_flags) > 0


# ---------------------------------------------------------------------------
# Layout classification constants
# ---------------------------------------------------------------------------

# A region that spans more than this fraction of page width is "full-width"
_FULL_WIDTH_RATIO = 0.70

# Minimum region count per column to consider a column valid
_MIN_REGIONS_PER_COLUMN = 2

# Y-margin fraction for header/footer detection
_HEADER_FOOTER_MARGIN = 0.08

# Maximum area ratio for a region to be considered "small / isolated"
_SMALL_REGION_AREA_RATIO = 0.005

# Overlap threshold for "overlapping" flag (as fraction of smaller region area)
_OVERLAP_THRESHOLD = 0.10

# Page types that are not text-body layouts
_NON_BODY_TYPES: set[RegionType] = {"header", "footer", "page_number", "figure"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_bbox(region: RegionIR) -> BBox | None:
    """Get bbox from region, falling back to children."""
    if region.bbox is not None:
        return region.bbox
    if region.polygon is not None:
        return region.polygon.bbox
    # Try children
    for child in region.children:
        if child.bbox is not None:
            return child.bbox
        if child.polygon is not None:
            return child.polygon.bbox
    return None


def _region_center_x(region: RegionIR, page_width: float) -> float:
    """Get normalized x-center (0–1) of a region."""
    bbox = _safe_bbox(region)
    if bbox is None or page_width <= 0:
        return 0.5
    return (bbox.x0 + bbox.x1) / 2.0 / page_width


def _region_center_y(region: RegionIR, page_height: float) -> float:
    """Get normalized y-center (0–1) of a region."""
    bbox = _safe_bbox(region)
    if bbox is None or page_height <= 0:
        return 0.5
    return (bbox.y0 + bbox.y1) / 2.0 / page_height


def _region_width_ratio(region: RegionIR, page_width: float) -> float:
    """Get region width as fraction of page width."""
    bbox = _safe_bbox(region)
    if bbox is None or page_width <= 0:
        return 0.0
    return (bbox.x1 - bbox.x0) / page_width


def _region_area_ratio(region: RegionIR, page_width: float, page_height: float) -> float:
    """Get region area as fraction of page area."""
    bbox = _safe_bbox(region)
    if bbox is None or page_width <= 0 or page_height <= 0:
        return 0.0
    return (bbox.width * bbox.height) / (page_width * page_height)


def _is_header_or_footer(region: RegionIR, page_height: float) -> str | None:
    """Check if a region is likely header/footer based on y-position.

    Returns ``"header"``, ``"footer"``, or ``None``.
    """
    bbox = _safe_bbox(region)
    if bbox is None or page_height <= 0:
        return None
    margin = page_height * _HEADER_FOOTER_MARGIN
    if bbox.y1 <= margin and bbox.y0 < margin * 0.5:
        return "header"
    if bbox.y0 >= page_height - margin and bbox.y1 > page_height - margin * 0.5:
        return "footer"
    return None


def _is_watermark(region: RegionIR, page_width: float, page_height: float) -> bool:
    """Detect likely watermark: centered, low confidence, semi-transparent-like."""
    bbox = _safe_bbox(region)
    if bbox is None or page_width <= 0 or page_height <= 0:
        return False
    cx = (bbox.x0 + bbox.x1) / 2.0 / page_width
    cy = (bbox.y0 + bbox.y1) / 2.0 / page_height
    # Watermarks are typically large, centered, low-confidence
    is_centered = 0.3 <= cx <= 0.7 and 0.3 <= cy <= 0.7
    is_large = (bbox.width * bbox.height) / (page_width * page_height) > 0.3
    is_low_conf = region.confidence < 0.3
    return is_centered and is_large and is_low_conf


def _rectangles_overlap(a: BBox, b: BBox) -> bool:
    """Check if two bboxes overlap by at least 10% of the smaller area."""
    ix0 = max(a.x0, b.x0)
    iy0 = max(a.y0, b.y0)
    ix1 = min(a.x1, b.x1)
    iy1 = min(a.y1, b.y1)
    if ix0 >= ix1 or iy0 >= iy1:
        return False
    overlap_area = (ix1 - ix0) * (iy1 - iy0)
    min_area = min(a.area, b.area)
    return min_area > 0 and (overlap_area / min_area) >= _OVERLAP_THRESHOLD


# ---------------------------------------------------------------------------
# Column detection
# ---------------------------------------------------------------------------


@dataclass
class _ColumnCluster:
    """A detected column cluster."""
    index: int
    x_center: float      # mean x-center of regions in this column
    region_ids: list[str]


def _detect_columns(
    regions: list[RegionIR],
    page_width: float,
    page_height: float,
) -> tuple[list[_ColumnCluster], list[str]]:
    """Detect column layout from region x-distribution.

    Returns (clusters, risk_flags).

    Algorithm:
    1. Filter body regions (exclude known headers/footers/watermarks).
    2. For each region, compute its x-center normalized to page width.
    3. Compute x-center histogram with 5 bins. Count regions per bin.
    4. Determine column count from histogram peaks.
    5. Assign each region to the nearest column peak.
    """
    risk_flags: list[str] = []

    # Filter to body regions that have geometry
    body_regions = []
    for r in regions:
        bbox = _safe_bbox(r)
        if bbox is None:
            continue
        if r.region_type in ("header", "footer", "page_number"):
            continue
        if _is_watermark(r, page_width, page_height):
            continue
        body_regions.append(r)

    if len(body_regions) < 3:
        # Too few regions to detect columns — single column
        clusters = [_ColumnCluster(index=0, x_center=0.5, region_ids=[r.region_id for r in body_regions])]
        return clusters, risk_flags

    # Compute x-centers for all body regions
    x_centers = [_region_center_x(r, page_width) for r in body_regions]

    # Histogram-based column detection: 5 bins across page width
    n_bins = 5
    bin_counts = [0] * n_bins
    bin_centers = [(i + 0.5) / n_bins for i in range(n_bins)]
    for cx in x_centers:
        bin_idx = min(int(cx * n_bins), n_bins - 1)
        bin_counts[bin_idx] += 1

    # Find non-empty bins (with at least _MIN_REGIONS_PER_COLUMN regions)
    col_bins = [i for i, cnt in enumerate(bin_counts) if cnt >= _MIN_REGIONS_PER_COLUMN]

    if not col_bins:
        # No clear column structure
        clusters = [_ColumnCluster(index=0, x_center=0.5, region_ids=[r.region_id for r in body_regions])]
        risk_flags.append("column_count_ambiguous")
        return clusters, risk_flags

    # Merge adjacent bins
    grouped: list[list[int]] = []
    current = [col_bins[0]]
    for b in col_bins[1:]:
        if b - current[-1] <= 1:
            current.append(b)
        else:
            grouped.append(current)
            current = [b]
    grouped.append(current)

    # Compute column x-centers from grouped bins
    columns: list[_ColumnCluster] = []
    for g_idx, group in enumerate(grouped):
        if len(group) == 1:
            center = bin_centers[group[0]]
        else:
            centers = [bin_centers[b] for b in group]
            center = statistics.mean(centers)
        columns.append(_ColumnCluster(index=g_idx, x_center=center, region_ids=[]))

    # If single column, check if it's truly single or ambiguous
    if len(columns) == 1:
        # Check spread: if regions span the full width, it's single column
        # If they cluster on one side, it could be ambiguous
        spread = max(x_centers) - min(x_centers)
        if spread < 0.4:
            risk_flags.append("column_count_ambiguous")

    # If 2+ columns, verify they're well-separated
    if len(columns) >= 2:
        for i in range(len(columns) - 1):
            gap = columns[i + 1].x_center - columns[i].x_center
            if gap < 0.15:
                risk_flags.append("column_count_ambiguous")

    return columns, risk_flags


def _assign_regions_to_columns(
    regions: list[RegionIR],
    columns: list[_ColumnCluster],
    page_width: float,
) -> dict[str, int]:
    """Assign each region to the nearest column cluster.

    Returns dict mapping region_id → column_index.
    Full-width regions (cross-column titles) get special handling.
    """
    assignments: dict[str, int] = {}

    for region in regions:
        bbox = _safe_bbox(region)
        if bbox is None:
            continue

        width_ratio = _region_width_ratio(region, page_width)

        # Cross-column titles span most of the page
        if width_ratio >= _FULL_WIDTH_RATIO and len(columns) > 1:
            # Assign to column -1 (special: spans all columns)
            # In ordering, these come before the first column's content
            assignments[region.region_id] = -1
            continue

        # For single column or one column cluster: assign to column 0
        if len(columns) == 1:
            assignments[region.region_id] = 0
            continue

        # Multi-column: find nearest column by x-center
        cx = _region_center_x(region, page_width)
        nearest = min(range(len(columns)), key=lambda i: abs(cx - columns[i].x_center))
        assignments[region.region_id] = nearest
        columns[nearest].region_ids.append(region.region_id)

    return assignments


# ---------------------------------------------------------------------------
# Main resolver
# ---------------------------------------------------------------------------


class ReadingOrderResolver:
    """Rule-based reading order resolver.

    Pure-functional: same input always produces same output.
    Deterministic regardless of input region order (sorts internally).
    """

    def resolve(self, page: PageIR) -> ReadingOrderResult:
        """Resolve reading order for all regions on a page.

        Args:
            page: PageIR containing regions with bbox geometry.

        Returns:
            ReadingOrderResult with ordered region IDs, edges, and risk flags.
        """
        risk_flags: list[str] = []
        edges: list[ReadingOrderEdge] = []

        if not page.regions:
            return ReadingOrderResult(
                ordered_region_ids=[],
                edges=[],
                confidence=1.0,
                strategy="single_column",
                risk_flags=[],
            )

        # Step 1: Separate body regions from headers/footers/watermarks
        body_regions: list[RegionIR] = []
        header_footer_ids: list[str] = []
        watermark_ids: list[str] = []

        for region in page.regions:
            bbox = _safe_bbox(region)
            if bbox is None:
                continue
            hf = _is_header_or_footer(region, page.height)
            if hf:
                header_footer_ids.append(region.region_id)
                region.flags.add(hf)
                continue
            if _is_watermark(region, page.width, page.height):
                watermark_ids.append(region.region_id)
                region.flags.add("watermark")
                continue
            body_regions.append(region)

        if header_footer_ids:
            risk_flags.append("reading_order_low_confidence")

        # Step 2: Detect columns
        columns, col_risk_flags = _detect_columns(body_regions, page.width, page.height)
        risk_flags.extend(col_risk_flags)

        # Step 3: Assign regions to columns
        column_assignments = _assign_regions_to_columns(body_regions, columns, page.width)

        # Step 4: Check for overlapping regions
        for i in range(len(body_regions)):
            for j in range(i + 1, len(body_regions)):
                a_bbox = _safe_bbox(body_regions[i])
                b_bbox = _safe_bbox(body_regions[j])
                if a_bbox is not None and b_bbox is not None:
                    if _rectangles_overlap(a_bbox, b_bbox):
                        risk_flags.append("overlapping_regions")
                        break
            else:
                continue
            break  # One detection is enough for the flag

        # Step 5: Check for isolated small regions
        for region in body_regions:
            area_ratio = _region_area_ratio(region, page.width, page.height)
            if 0 < area_ratio < _SMALL_REGION_AREA_RATIO:
                risk_flags.append("isolated_region")
                break

        # Step 6: Determine strategy
        n_cols = len(columns)
        if n_cols <= 1:
            strategy = "single_column"
        elif n_cols == 2:
            strategy = "double_column"
        else:
            strategy = "multi_column"

        # Step 7: Order regions
        # Group: cross-column titles first, then each column left-to-right
        # Within group: sort by y-center (top-to-bottom)
        ordered_ids = self._order_regions(
            body_regions=body_regions,
            column_assignments=column_assignments,
            columns=columns,
        )

        # Step 8: Build edges
        for i in range(len(ordered_ids) - 1):
            edges.append(ReadingOrderEdge(
                source_region_id=ordered_ids[i],
                target_region_id=ordered_ids[i + 1],
                confidence=0.9 if n_cols <= 1 else 0.7,
                reason=f"column_{strategy}_order",
            ))

        # Append headers/footers/watermarks at the end (excluded from main order)
        # (These don't participate in the reading order proper)
        for hid in header_footer_ids:
            if hid not in ordered_ids:
                ordered_ids.append(hid)
        for wid in watermark_ids:
            if wid not in ordered_ids:
                ordered_ids.append(wid)

        # Confidence: higher for single-column, lower for complex layouts
        confidence = self._compute_confidence(strategy, n_cols, risk_flags)

        # Deduplicate risk flags
        risk_flags = list(dict.fromkeys(risk_flags))

        return ReadingOrderResult(
            ordered_region_ids=ordered_ids,
            edges=edges,
            confidence=confidence,
            strategy=strategy,
            risk_flags=risk_flags,
            column_assignments=column_assignments,
        )

    def _order_regions(
        self,
        body_regions: list[RegionIR],
        column_assignments: dict[str, int],
        columns: list[_ColumnCluster],
    ) -> list[str]:
        """Order regions by (column_group, y_center).

        Cross-column titles (col=-1) come first.
        Then columns left-to-right, each column top-to-bottom.
        """
        if not body_regions:
            return []

        # Sort body regions by (column_assignment, y_center)
        def _sort_key(region: RegionIR) -> tuple[int, float, float]:
            col = column_assignments.get(region.region_id, 0)
            y_center = _region_center_y(region, 1000)  # normalize not needed for sort
            x_center = _region_center_x(region, 1000)
            return (col, y_center, x_center)

        sorted_regions = sorted(body_regions, key=_sort_key)
        return [r.region_id for r in sorted_regions]

    def _compute_confidence(
        self,
        strategy: str,
        column_count: int,
        risk_flags: list[str],
    ) -> float:
        """Compute overall confidence for the reading order result."""
        base = {
            "single_column": 0.95,
            "double_column": 0.80,
            "multi_column": 0.65,
        }.get(strategy, 0.5)

        # Penalize each risk flag
        penalty_per_flag = 0.05
        effective_penalty = len(risk_flags) * penalty_per_flag

        return max(0.1, base - effective_penalty)

    def resolve_multi_page(
        self,
        pages: list[PageIR],
    ) -> list[ReadingOrderResult]:
        """Resolve reading order for multiple pages."""
        return [self.resolve(page) for page in pages]


# ---------------------------------------------------------------------------
# Convenience function: apply reading order to PageIR
# ---------------------------------------------------------------------------


def apply_reading_order(
    page: PageIR,
    resolver: ReadingOrderResolver | None = None,
) -> ReadingOrderResult:
    """Resolve and apply reading order to a PageIR in place.

    Updates:
    - ``page.reading_order`` — ordered list of region IDs
    - ``page.reading_order_confidence``
    - ``page.reading_order_flags``
    - Each region's ``.reading_order`` field with its position

    Returns the ReadingOrderResult for inspection.
    """
    if resolver is None:
        resolver = ReadingOrderResolver()
    result = resolver.resolve(page)

    page.reading_order = list(result.ordered_region_ids)
    page.reading_order_confidence = result.confidence
    page.reading_order_flags = list(result.risk_flags)

    # Update individual region reading_order indices
    for idx, region_id in enumerate(result.ordered_region_ids):
        for region in page.regions:
            if region.region_id == region_id:
                region.reading_order = idx
                break

    return result


# ---------------------------------------------------------------------------
# Shuffle test helper
# ---------------------------------------------------------------------------


def shuffle_regions(page: PageIR, seed: int) -> PageIR:
    """Create a copy of a PageIR with regions shuffled (for determinism tests).

    Uses a deterministic pseudo-random shuffle based on ``seed``.
    """
    import copy
    page_copy = copy.deepcopy(page)
    regions = list(page_copy.regions)
    # Deterministic shuffle
    import hashlib
    regions.sort(key=lambda r: hashlib.sha256(
        f"{r.region_id}:{seed}".encode()
    ).hexdigest())
    page_copy.regions = regions
    return page_copy
