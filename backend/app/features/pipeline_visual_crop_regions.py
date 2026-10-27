"""Reconstruct visual regions and project their image/table fallbacks."""

from __future__ import annotations

from typing import Any

from app.features.pipeline_visual_crop_state import VisualCropState


async def project_question_regions(state: VisualCropState, q: dict) -> str:
    seen_region_ids: set[str] = set()
    segments: list[dict] = list(q.get("segments") or [])
    stem = q.get("stem") or (q.get("parsed_content") or {}).get("text") or ""
    vrs = list(q.get("visual_regions") or [])
    for vr_dict in vrs:
        region_id = vr_dict.get("region_id", "")
        if region_id and region_id in seen_region_ids:
            continue
        if region_id:
            seen_region_ids.add(region_id)
        region, rt, region_types = reconstruct_region(vr_dict, region_id, state.visual_region_type)
        if region.bbox:
            region = await state.crop_and_upload_region(
                state.page_image_refs, region, state.virtual_import_id
            )
        if region.image_url:
            append_region_image(state, segments, region, region_id, rt, region_types)
        else:
            flag_region_failure(q, region)
    if segments:
        q["segments"] = segments
        q["parsed_content"] = {
            **(q.get("parsed_content") or {}),
            "render_mode": "segments",
            "segments": segments,
        }
    return stem


def reconstruct_region(
    vr_dict: dict, region_id: str, visual_region_type: Any
) -> tuple[Any, Any, Any]:
    from app.services.visual_region_types import CoordinateSpace, VisualRegionType

    bbox = vr_dict.get("bbox")
    region_type_str = vr_dict.get("region_type", "unknown")
    try:
        rt = VisualRegionType(region_type_str)
    except ValueError:
        rt = VisualRegionType.UNKNOWN
    crs = vr_dict.get("coordinate_space", "image_pixels")
    try:
        cs = CoordinateSpace(crs) if crs else CoordinateSpace.IMAGE_PIXELS
    except ValueError:
        cs = CoordinateSpace.IMAGE_PIXELS
    region = visual_region_type(
        region_id=region_id,
        region_type=rt,
        source_page=vr_dict.get("source_page", 1),
        bbox=tuple(bbox) if isinstance(bbox, (list, tuple)) and len(bbox) == 4 else None,
        coordinate_space=cs,
        confidence=vr_dict.get("confidence", 0.5),
        alt=vr_dict.get("alt", ""),
        option_key=vr_dict.get("option_key"),
        requires_review=bool(vr_dict.get("requires_review", True)),
    )
    return region, rt, VisualRegionType


def append_region_image(
    state: VisualCropState,
    segments: list[dict],
    region: Any,
    region_id: str,
    rt: Any,
    region_types: Any,
) -> None:
    seg = region.to_segment()
    matching_tables = []
    if rt == region_types.TABLE:
        for existing in segments:
            if existing.get("type") == "table" and existing.get("region_id") == region_id:
                matching_tables.append(existing)
                existing["source_image_url"] = region.image_url
                existing["fallback_image_url"] = region.image_url
    should_append_image = (
        rt != region_types.TABLE
        or not matching_tables
        or any(table.get("requires_review") for table in matching_tables)
    )
    if should_append_image and not any(
        existing.get("type") == seg.get("type")
        and existing.get("region_id") == region_id
        and existing.get("url") == region.image_url
        for existing in segments
    ):
        segments.append(seg)
    state.crop_warnings.append(f"visual region {region_id} cropped for page {region.source_page}")


def flag_region_failure(q: dict, region: Any) -> None:
    flags = list(q.get("risk_flags") or [])
    if region.crop_failed:
        if "visual_crop_failed" not in flags:
            flags.append("visual_crop_failed")
    elif region.bbox is None:
        if "visual_region_bbox_missing" not in flags:
            flags.append("visual_region_bbox_missing")
    q["risk_flags"] = flags
