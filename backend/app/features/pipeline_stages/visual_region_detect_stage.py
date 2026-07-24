"""Visual region detection stage — page-level detection of diagrams, charts, tables, figures.

This stage runs BEFORE visual_region_assign_stage. It detects visual regions
from PaddleOCR-VL layout_blocks and other sources, but does NOT assign them
to specific questions yet. Assignment happens in a later stage after split/match.

Key behaviors:
- Detects figures, diagrams, charts, tables from layout_blocks
- Normalizes region_type, bbox, coordinate_space, confidence
- Filters noise: logos, watermarks, headers, footers, full-page backgrounds
- Does NOT upload/crop yet — cropping happens in visual_region_assign_stage
- Attaches visual_regions to question dict for downstream handling
"""

from __future__ import annotations

import logging

from app.features.pipeline_stages._helpers import _count_risk_flags
from app.services.visual_region_types import (
    VisualRegion,
    VisualRegionType,
)

logger = logging.getLogger(__name__)


# Block types from PaddleOCR-VL that indicate visual content worth preserving
_VISUAL_BLOCK_TYPES = frozenset({
    "figure", "fig", "diagram", "chart", "graph", "illustration",
    "table", "table_image", "photo", "image", "picture",
    "figure_caption", "table_caption",
})

# Block types that should be filtered (noise)
_NOISE_BLOCK_TYPES = frozenset({
    "header", "footer", "page_number", "page_num",
    "watermark", "logo", "stamp", "decoration", "separator",
    "line", "shape", "advertisement",
})

# Page area ratio threshold for "full-page" detection (region covers > 80% of page)
_FULL_PAGE_RATIO = 0.80

# Minimum visual region area in normalized_1000^2 units
_MIN_REGION_AREA = 50 * 50

# Page edge margin ratio (regions within this margin are edge candidates)
_PAGE_EDGE_MARGIN = 0.05


def run_visual_region_detect_stage(
    questions: list[dict],
    *,
    layout_blocks_by_page: dict[int, list[dict]] | None = None,
    page_dimensions: dict[int, tuple[int, int]] | None = None,
) -> dict:
    """Page-level detection of visual regions from layout_blocks.

    Args:
        questions: Pipeline question dicts
        layout_blocks_by_page: Page index → list of normalized layout blocks
        page_dimensions: Page index → (width, height) in pixels

    Returns:
        dict with ``questions``, ``warnings``, ``risk_flag_counts`` keys.
    """
    if not questions:
        return {"questions": questions, "warnings": ["visual_region_detect: empty questions"]}

    warnings: list[str] = []
    region_count = 0

    if not layout_blocks_by_page:
        warnings.append("visual_region_detect: no layout_blocks available")
        return {"questions": questions, "warnings": warnings, "risk_flag_counts": _count_risk_flags(questions)}

    # Page-level detection: process all layout blocks and create VisualRegions
    all_regions: list[VisualRegion] = []
    for page_idx, blocks in layout_blocks_by_page.items():
        page_w, page_h = page_dimensions.get(page_idx, (1000, 1000)) if page_dimensions else (1000, 1000)
        page_regions = _detect_page_regions(blocks, page_idx, page_w, page_h)
        all_regions.extend(page_regions)

    if not all_regions:
        warnings.append("visual_region_detect: no visual regions found")
        return {"questions": questions, "warnings": warnings, "risk_flag_counts": _count_risk_flags(questions)}

    region_count = len(all_regions)
    logger.info(
        "visual_region_detect: %d regions detected across %d pages",
        region_count, len(layout_blocks_by_page),
    )

    # Attach unassigned regions to question dicts for downstream assignment
    # Each question gets its page's regions as a reference
    regions_by_page: dict[int, list[VisualRegion]] = {}
    for vr in all_regions:
        regions_by_page.setdefault(vr.source_page, []).append(vr)

    for q in questions:
        page = q.get("page_start") or 1
        q_regions = regions_by_page.get(page, [])
        if not q_regions:
            continue
        # Store as dicts for JSON serialization downstream
        q_visual_regions: list[dict] = list(q.get("visual_regions") or [])
        for vr in q_regions:
            vr_dict = vr.to_dict()
            # Don't duplicate across questions — just attach for now
            if not any(r.get("region_id") == vr.region_id for r in q_visual_regions):
                q_visual_regions.append(vr_dict)
        if q_visual_regions:
            q["visual_regions"] = q_visual_regions
            flags = list(q.get("risk_flags") or [])
            if "visual_region_detected" not in flags:
                flags.append("visual_region_detected")
            q["risk_flags"] = flags

    warnings.append(
        f"visual_region_detect: {region_count} regions, "
        f"{len(regions_by_page)} pages affected"
    )

    return {
        "questions": questions,
        "warnings": warnings,
        "risk_flag_counts": _count_risk_flags(questions),
    }


def _detect_page_regions(
    blocks: list[dict],
    page_idx: int,
    page_width: int,
    page_height: int,
) -> list[VisualRegion]:
    """Detect visual regions from normalized layout blocks on one page."""
    regions: list[VisualRegion] = []

    for block in blocks:
        block_type = (block.get("type") or block.get("label") or "").lower()
        bbox = block.get("bbox")

        # Skip noise blocks
        if block_type in _NOISE_BLOCK_TYPES:
            continue

        # Skip non-visual text blocks
        if not bbox:
            continue

        # Check if this is a visual block worth preserving
        is_visual = block_type in _VISUAL_BLOCK_TYPES
        if not is_visual:
            # For text blocks, skip — they're handled by the text pipeline
            continue

        # Check if region is too small (likely noise)
        try:
            x0, y0, x1, y1 = bbox
            area = (x1 - x0) * (y1 - y0)
        except (ValueError, TypeError):
            continue
        if area < _MIN_REGION_AREA:
            continue

        # Check if region covers almost full page (likely a page background/image)
        page_area = page_width * page_height
        if page_area > 0 and area / page_area > _FULL_PAGE_RATIO:
            continue

        # Check if region is at page edge (likely decoration/header/footer)
        edge_margin_x = page_width * _PAGE_EDGE_MARGIN
        edge_margin_y = page_height * _PAGE_EDGE_MARGIN
        if x0 < edge_margin_x and y0 < edge_margin_y:
            continue  # top-left corner decoration
        if x1 > page_width - edge_margin_x and y0 < edge_margin_y:
            continue  # top-right corner decoration

        # Classify region type
        region_type = _classify_region_type(block_type, block)

        region_id = VisualRegion.generate_region_id(page_idx, tuple(bbox))

        vr = VisualRegion(
            region_id=region_id,
            region_type=region_type,
            source_page=page_idx,
            bbox=tuple(bbox),
            coordinate_space="normalized_1000",  # default VL space
            confidence=block.get("confidence", 0.5),
            alt=block.get("text", "")[:200],
            raw_data=block,
        )
        regions.append(vr)

    return regions


def _classify_region_type(
    block_type: str,
    block: dict,
) -> VisualRegionType:
    """Map a layout block type to a VisualRegionType."""
    type_map = {
        "figure": VisualRegionType.DIAGRAM,
        "fig": VisualRegionType.DIAGRAM,
        "diagram": VisualRegionType.DIAGRAM,
        "chart": VisualRegionType.CHART,
        "graph": VisualRegionType.CHART,
        "table": VisualRegionType.TABLE,
        "table_image": VisualRegionType.TABLE,
        "photo": VisualRegionType.ILLUSTRATION,
        "image": VisualRegionType.ILLUSTRATION,
        "picture": VisualRegionType.ILLUSTRATION,
        "illustration": VisualRegionType.ILLUSTRATION,
        "figure_caption": VisualRegionType.DIAGRAM,
        "table_caption": VisualRegionType.TABLE,
        "equation": VisualRegionType.FORMULA,
        "formula": VisualRegionType.FORMULA,
        "code": VisualRegionType.CODE,
    }
    return type_map.get(block_type, VisualRegionType.UNKNOWN)
