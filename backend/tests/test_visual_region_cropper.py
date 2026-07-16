"""Tests for visual_region_cropper — coordinate-aware cropping.

Covers:
- bbox validation (valid, invalid, None, out of bounds)
- coordinate space conversion (pdf_points, image_pixels, normalized_1000, normalized_1)
- empty crop region raises EmptyCropError
- actual cropping from a synthetic test image
"""
from __future__ import annotations

import io
import os
import tempfile

import pytest
from PIL import Image, ImageDraw

from app.services.visual_region_cropper import (
    EmptyCropError,
    OversizedCropError,
    convert_bbox,
    crop_region,
    crop_from_page_ref_compat,
    validate_bbox,
)
from app.services.visual_region_types import CoordinateSpace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_test_image(width: int = 800, height: int = 600) -> str:
    """Create a synthetic test image with a colored rectangle in the center."""
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    # Draw a red rectangle from (200,150) to (600,450)
    draw.rectangle([200, 150, 600, 450], fill="red", outline="black")
    draw.text((50, 50), "Stem text above", fill="black")
    draw.text((50, 500), "Stem text below", fill="black")
    draw.text((250, 30), "A. Option A", fill="black")
    draw.text((250, 550), "D. Option D", fill="black")
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    img.save(tmp.name)
    return tmp.name


# ---------------------------------------------------------------------------
# validate_bbox
# ---------------------------------------------------------------------------


class TestValidateBbox:
    def test_valid_bbox(self):
        assert validate_bbox((100, 100, 500, 400)) == (100, 100, 500, 400)

    def test_valid_bbox_list_input(self):
        assert validate_bbox([100, 100, 500, 400]) == (100, 100, 500, 400)

    def test_none_bbox(self):
        assert validate_bbox(None) is None

    def test_empty_bbox(self):
        assert validate_bbox(()) is None

    def test_wrong_length(self):
        assert validate_bbox((1, 2, 3)) is None

    def test_negative_coord(self):
        assert validate_bbox((-10, 100, 500, 400)) is None

    def test_reversed_bbox(self):
        assert validate_bbox((500, 100, 100, 400)) is None  # x1 < x0

    def test_zero_area(self):
        assert validate_bbox((100, 100, 100, 400)) is None  # x1 == x0

    def test_huge_bbox(self):
        assert validate_bbox((0, 0, 2_000_000, 2_000_000)) is None

    def test_non_numeric(self):
        assert validate_bbox(("a", "b", "c", "d")) is None


# ---------------------------------------------------------------------------
# convert_bbox
# ---------------------------------------------------------------------------


class TestConvertBbox:
    def test_image_pixels_no_change(self):
        result = convert_bbox((100, 200, 500, 400), "image_pixels", 800, 600)
        assert result == (100, 200, 500, 400)

    def test_normalized_1000(self):
        # (100, 200, 500, 400) in 0-1000 space at 800x600 image
        result = convert_bbox((100, 200, 500, 400), "normalized_1000", 800, 600)
        assert result == (80, 120, 400, 240)

    def test_normalized_1(self):
        result = convert_bbox((0.1, 0.2, 0.5, 0.4), "normalized_1", 800, 600)
        assert result == (80, 120, 400, 240)

    def test_clamp_to_image_bounds(self):
        result = convert_bbox((100, 200, 900, 700), "image_pixels", 800, 600)
        assert result == (100, 200, 800, 600)

    def test_coordinate_space_enum(self):
        result = convert_bbox((100, 200, 500, 400), CoordinateSpace.IMAGE_PIXELS, 800, 600)
        assert result == (100, 200, 500, 400)

    def test_unknown_space_treated_as_pixels(self):
        result = convert_bbox((100, 200, 500, 400), "unknown_space", 800, 600)
        assert result == (100, 200, 500, 400)


# ---------------------------------------------------------------------------
# crop_region with real image
# ---------------------------------------------------------------------------


class TestCropRegion:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.test_image_path = _make_test_image(800, 600)
        yield
        if os.path.exists(self.test_image_path):
            os.unlink(self.test_image_path)

    def test_crop_valid_region(self):
        """Crop the red rectangle area and verify it's not the full page."""
        png_bytes = crop_region(
            self.test_image_path,
            (200, 150, 600, 450),
            coordinate_space=CoordinateSpace.IMAGE_PIXELS,
        )
        assert len(png_bytes) > 0
        # Verify it's a valid PNG
        assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
        # Verify cropped size is NOT 800x600 (not full page)
        cropped = Image.open(io.BytesIO(png_bytes))
        assert cropped.width < 800
        assert cropped.height < 600

    def test_crop_too_small_raises(self):
        """Bbox that, after padding, is still too small should raise EmptyCropError."""
        # Without padding, (100, 100, 101, 101) is just 1x1
        # With 6pt padding at 150/72 scale = ~12.5px, becomes ~(87,87,114,114) = 27x27
        # But padding is applied to the bbox before coordinate conversion,
        # so the final size depends on coordinate space.
        # Use image_pixels space with 0 padding so 1x1 stays 1x1
        with pytest.raises(EmptyCropError):
            crop_region(
                self.test_image_path,
                (100, 100, 101, 101),  # 1x1
                coordinate_space=CoordinateSpace.IMAGE_PIXELS,
                padding_pt=0.0,
            )

    def test_crop_nonexistent_file_raises(self):
        with pytest.raises(Exception):
            crop_region(
                "/nonexistent/path.png",
                (100, 100, 500, 400),
                coordinate_space=CoordinateSpace.IMAGE_PIXELS,
            )

    def test_crop_from_page_ref_compat(self):
        """Legacy compat wrapper with pdf_points space."""
        png_bytes = crop_from_page_ref_compat(
            self.test_image_path,
            (200, 150, 600, 450),
            page_image_width=800,
            page_image_height=600,
        )
        assert len(png_bytes) > 0
        assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"

    def test_crop_idempotent_same_result(self):
        """Same bbox and page should produce same crop (content hash equality)."""
        import hashlib

        bbox = (200, 150, 600, 450)
        result1 = crop_region(
            self.test_image_path, bbox,
            coordinate_space=CoordinateSpace.IMAGE_PIXELS,
        )
        result2 = crop_region(
            self.test_image_path, bbox,
            coordinate_space=CoordinateSpace.IMAGE_PIXELS,
        )
        assert hashlib.md5(result1).hexdigest() == hashlib.md5(result2).hexdigest()


# ---------------------------------------------------------------------------
# VisualRegion
# ---------------------------------------------------------------------------


class TestVisualRegionType:
    def test_region_types_enum_values(self):
        from app.services.visual_region_types import VisualRegionType, SegmentType
        assert VisualRegionType.DIAGRAM.value == "diagram"
        assert VisualRegionType.CHART.value == "chart"
        assert VisualRegionType.TABLE.value == "table"
        assert VisualRegionType.FORMULA.value == "formula"
        assert SegmentType.IMAGE.value == "image"
        assert SegmentType.MATH_IMAGE.value == "math_image"
        assert SegmentType.TABLE_IMAGE.value == "table_image"

    def test_visual_reference_detection(self):
        from app.services.visual_region_types import contains_visual_reference
        assert contains_visual_reference("如图所示") is True
        assert contains_visual_reference("如下图") is True
        assert contains_visual_reference("从图中") is True
        assert contains_visual_reference("普通文本") is False
        assert contains_visual_reference(None) is False
        assert contains_visual_reference("") is False
