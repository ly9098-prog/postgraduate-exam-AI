"""Coordinate-aware visual region cropper.

Supports multiple coordinate spaces and provides safe, validated cropping
from rendered page images. Used by visual_region_detect_stage and
math_detect_stage (via delegation from formula_image_cropper).
"""

from __future__ import annotations

import hashlib
import io
import logging
from datetime import datetime

from app.core.executor_registry import get_executor
from app.services.visual_region_types import (
    CoordinateSpace,
    VisualRegion,
)

logger = logging.getLogger(__name__)

# Default padding in PDF points (applied before coordinate conversion)
_DEFAULT_PADDING_PT = 6.0

# Default page render DPI (same as pipeline_orchestrator._render_page_images)
_PAGE_RENDER_DPI = 150

# Max output dimensions
_MAX_CROP_WIDTH = 4096
_MAX_CROP_HEIGHT = 4096
_MAX_CROP_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

# Allowed MIME types for uploaded images
ALLOWED_IMAGE_MIME_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})

# Minimum crop dimensions (any smaller is likely noise)
_MIN_CROP_WIDTH = 16
_MIN_CROP_HEIGHT = 16


class CropError(Exception):
    """Raised when cropping fails for a non-recoverable reason."""


class EmptyCropError(CropError):
    """Cropped region would be empty (bbox out of bounds or zero area)."""


class OversizedCropError(CropError):
    """Cropped region exceeds maximum allowed dimensions."""


def validate_bbox(
    bbox: tuple[float, float, float, float] | list[float] | None,
) -> tuple[float, float, float, float] | None:
    """Validate and normalize a bbox.

    Returns a tuple of (x0, y0, x1, y1) or None if invalid.
    """
    if bbox is None:
        return None
    if isinstance(bbox, list):
        bbox = tuple(bbox)
    if not isinstance(bbox, tuple) or len(bbox) != 4:
        return None
    x0, y0, x1, y1 = bbox
    if not all(isinstance(v, (int, float)) for v in (x0, y0, x1, y1)):
        return None
    if x1 <= x0 or y1 <= y0:
        return None
    if not all(v >= 0 for v in (x0, y0, x1, y1)):
        return None
    # Sanity check: reasonable coordinates (prevents absurd values)
    if any(v > 1_000_000 for v in (x0, y0, x1, y1)):
        return None
    return (x0, y0, x1, y1)


def convert_bbox(
    bbox: tuple[float, float, float, float],
    source_space: CoordinateSpace | str,
    page_image_width: int,
    page_image_height: int,
    page_pdf_width: float | None = None,
    page_pdf_height: float | None = None,
) -> tuple[int, int, int, int]:
    """Convert bbox from source coordinate space to image pixel coordinates.

    Args:
        bbox: (x0, y0, x1, y1) in source coordinate space
        source_space: One of CoordinateSpace enum values
        page_image_width: Width of the rendered page image in pixels
        page_image_height: Height of the rendered page image in pixels
        page_pdf_width: PDF page width in points (required for pdf_points source)
        page_pdf_height: PDF page height in points (required for pdf_points source)

    Returns:
        (x0, y0, x1, y1) in image pixel coordinates, clamped to image bounds
    """
    x0, y0, x1, y1 = bbox
    source = source_space.value if isinstance(source_space, CoordinateSpace) else source_space

    if source == "image_pixels":
        # Already in image pixel space — use as-is
        scale_x = scale_y = 1.0

    elif source == "pdf_points":
        # PDF points (72 DPI) → page image pixels (e.g., 150 DPI)
        if page_pdf_width and page_pdf_height:
            scale_x = page_image_width / page_pdf_width
            scale_y = page_image_height / page_pdf_height
        else:
            # Fallback: assume standard render DPI
            scale_x = page_image_width / (page_image_width * 72 / _PAGE_RENDER_DPI)
            scale_y = page_image_height / (page_image_height * 72 / _PAGE_RENDER_DPI)
            logger.warning("convert_bbox: pdf_points without page_pdf dims — using fallback scale")

    elif source == "normalized_1000":
        # 0-1000 normalized → image pixels
        scale_x = page_image_width / 1000.0
        scale_y = page_image_height / 1000.0

    elif source == "normalized_1":
        # 0.0-1.0 normalized → image pixels
        scale_x = page_image_width
        scale_y = page_image_height

    else:
        raise ValueError(
            f"convert_bbox: unsupported coordinate_space={source!r} "
            f"(expected image_pixels|pdf_points|normalized_1000|normalized_1)"
        )

    return _clamp_bbox(
        int(x0 * scale_x),
        int(y0 * scale_y),
        int(x1 * scale_x),
        int(y1 * scale_y),
        page_image_width,
        page_image_height,
    )


def _clamp_bbox(
    x0: int, y0: int, x1: int, y1: int,
    max_w: int, max_h: int,
) -> tuple[int, int, int, int]:
    """Clamp bbox to image bounds and ensure minimum size."""
    x0 = max(0, x0)
    y0 = max(0, y0)
    x1 = min(max_w, x1)
    y1 = min(max_h, y1)
    return (x0, y0, x1, y1)


def crop_region(
    page_image_path: str,
    bbox: tuple[float, float, float, float],
    *,
    coordinate_space: CoordinateSpace | str = CoordinateSpace.IMAGE_PIXELS,
    page_image_width: int | None = None,
    page_image_height: int | None = None,
    page_pdf_width: float | None = None,
    page_pdf_height: float | None = None,
    padding_pt: float = _DEFAULT_PADDING_PT,
) -> bytes:
    """Crop a region from a rendered page image and return PNG bytes.

    Args:
        page_image_path: Path to the rendered page PNG/JPEG
        bbox: (x0, y0, x1, y1) in source coordinate space
        coordinate_space: Coordinate space of the bbox
        page_image_width: Width of rendered page image (read from file if None)
        page_image_height: Height of rendered page image (read from file if None)
        page_pdf_width: PDF page width in points (for pdf_points conversion)
        page_pdf_height: PDF page height in points (for pdf_points conversion)
        padding_pt: Extra padding in PDF points (applied via coordinate conversion)

    Returns:
        PNG bytes of the cropped region

    Raises:
        EmptyCropError: if crop region would be empty
        OversizedCropError: if crop exceeds MAX_CROP dimensions
        CropError: on other failures
    """
    from PIL import Image

    # Open the page image
    try:
        img = Image.open(page_image_path).convert("RGB")
    except FileNotFoundError:
        raise CropError(f"page image not found: {page_image_path}")
    except Exception as e:
        raise CropError(f"cannot open page image {page_image_path}: {e}")

    actual_w, actual_h = img.size
    pw = page_image_width or actual_w
    ph = page_image_height or actual_h

    # ── Compute coordinate-space-aware padding ──
    source = coordinate_space.value if isinstance(coordinate_space, CoordinateSpace) else coordinate_space

    if source == "pdf_points":
        pad_x = pad_y = padding_pt
    elif source == "image_pixels":
        if pw and ph and page_pdf_width and page_pdf_height:
            dpi_x = pw / page_pdf_width * 72 if page_pdf_width else _PAGE_RENDER_DPI
            dpi_y = ph / page_pdf_height * 72 if page_pdf_height else _PAGE_RENDER_DPI
        else:
            dpi_x = dpi_y = _PAGE_RENDER_DPI
        pad_x = padding_pt * dpi_x / 72.0
        pad_y = padding_pt * dpi_y / 72.0
    elif source == "normalized_1000":
        pdf_w = page_pdf_width or (pw * 72.0 / _PAGE_RENDER_DPI) if pw else 612
        pdf_h = page_pdf_height or (ph * 72.0 / _PAGE_RENDER_DPI) if ph else 792
        pad_x = padding_pt / pdf_w * 1000.0
        pad_y = padding_pt / pdf_h * 1000.0
    elif source == "normalized_1":
        pdf_w = page_pdf_width or (pw * 72.0 / _PAGE_RENDER_DPI) if pw else 612
        pdf_h = page_pdf_height or (ph * 72.0 / _PAGE_RENDER_DPI) if ph else 792
        pad_x = padding_pt / pdf_w
        pad_y = padding_pt / pdf_h
    else:
        raise ValueError(
            f"Unsupported coordinate_space: {source!r} "
            f"(expected pdf_points|image_pixels|normalized_1000|normalized_1)"
        )

    padded_bbox = (
        bbox[0] - pad_x,
        bbox[1] - pad_y,
        bbox[2] + pad_x,
        bbox[3] + pad_y,
    )

    # Convert to image pixel coordinates
    converted = convert_bbox(
        padded_bbox,
        coordinate_space,
        pw, ph,
        page_pdf_width, page_pdf_height,
    )

    x0, y0, x1, y1 = converted

    if x1 <= x0 or y1 <= y0:
        raise EmptyCropError(
            f"empty crop region after conversion: bbox={bbox} "
            f"converted=({x0},{y0},{x1},{y1})"
        )

    # Validate size limits
    crop_w = x1 - x0
    crop_h = y1 - y0
    if crop_w < _MIN_CROP_WIDTH or crop_h < _MIN_CROP_HEIGHT:
        raise EmptyCropError(
            f"crop too small: {crop_w}x{crop_h} (min {_MIN_CROP_WIDTH}x{_MIN_CROP_HEIGHT})"
        )

    if crop_w > _MAX_CROP_WIDTH or crop_h > _MAX_CROP_HEIGHT:
        raise OversizedCropError(
            f"crop too large: {crop_w}x{crop_h} (max {_MAX_CROP_WIDTH}x{_MAX_CROP_HEIGHT})"
        )

    # Crop and save to PNG bytes
    cropped = img.crop((x0, y0, x1, y1))
    buf = io.BytesIO()
    cropped.save(buf, format="PNG")
    result = buf.getvalue()

    if len(result) > _MAX_CROP_FILE_SIZE:
        raise OversizedCropError(
            f"crop file too large: {len(result)} bytes (max {_MAX_CROP_FILE_SIZE})"
        )

    return result


async def crop_and_upload_region(
    page_image_refs: dict[int, str],
    region: VisualRegion,
    import_id: int,
    *,
    page_pdf_width: float | None = None,
    page_pdf_height: float | None = None,
) -> VisualRegion:
    """Crop a single VisualRegion and upload to storage.

    Populates region.image_url on success, sets crop_failed on error.
    Idempotent: same page + bbox + coordinate_space produces same filename.
    """
    from app.services.storage_backend import get_storage

    page_path = page_image_refs.get(region.source_page)
    if not page_path:
        logger.warning(
            "crop_and_upload: no page image for page %d (import=%s)",
            region.source_page, import_id,
        )
        region.crop_failed = True
        region.risk_flags.append("visual_crop_failed")
        return region

    if region.bbox is None:
        logger.warning(
            "crop_and_upload: bbox is None for region %s (import=%s)",
            region.region_id, import_id,
        )
        region.crop_failed = True
        region.requires_review = True
        region.risk_flags.append("visual_region_bbox_missing")
        return region


    try:
        png_bytes = await get_executor("image").run(
            crop_region,
            page_path,
            region.bbox,
            coordinate_space=region.coordinate_space,
            page_pdf_width=page_pdf_width,
            page_pdf_height=page_pdf_height,
        )

        content_hash = hashlib.sha256(png_bytes).hexdigest()[:12]
        month = datetime.now().strftime("%Y%m")
        filename = f"{import_id}_p{region.source_page}_{content_hash}.png"

        storage = get_storage()
        url = await storage.upload(f"{month}/vr/{filename}", png_bytes)

        region.image_url = url
        region.crop_failed = False
    except (CropError, Exception) as e:
        logger.warning(
            "crop failed import=%s region=%s page=%s: %s",
            import_id, region.region_id, region.source_page, e,
        )
        region.crop_failed = True
        region.requires_review = True
        if "visual_crop_failed" not in region.risk_flags:
            region.risk_flags.append("visual_crop_failed")

    return region


async def crop_and_upload_regions(
    page_image_refs: dict[int, str],
    regions: list[VisualRegion],
    import_id: int,
    *,
    page_pdf_width: float | None = None,
    page_pdf_height: float | None = None,
) -> list[VisualRegion]:
    """Crop and upload multiple regions. Each failure is handled individually."""
    result: list[VisualRegion] = []
    for region in regions:
        cropped = await crop_and_upload_region(
            page_image_refs, region, import_id,
            page_pdf_width=page_pdf_width,
            page_pdf_height=page_pdf_height,
        )
        result.append(cropped)
    return result


def crop_from_page_ref_compat(
    page_image_path: str,
    bbox: tuple[float, float, float, float],
    *,
    page_image_width: int | None = None,
    page_image_height: int | None = None,
    padding_pt: float = _DEFAULT_PADDING_PT,
) -> bytes:
    """Legacy-compatible wrapper that assumes bbox is in PDF points (72 DPI).

    This replaces formula_image_cropper.crop_from_page_ref.
    """
    return crop_region(
        page_image_path,
        bbox,
        coordinate_space=CoordinateSpace.PDF_POINTS,
        page_image_width=page_image_width,
        page_image_height=page_image_height,
        padding_pt=padding_pt,
    )
