"""Pure-function compatibility baseline for visual region coordinate conversion.

Pins the four coordinate-space conversions (image_pixels, pdf_points with and
without page_pdf dims, normalized_1000, normalized_1), the unsupported-space
rejection, the int truncation semantics, the CoordinateSpace enum values, the
_CLAMP_BBOX bounds clamping behaviour, and the module-level constants so that
later refactors of the coordinate conversion logic cannot silently change which
pixel region a given source-space bbox maps to. The existing
``test_visual_region_cropper_compatibility.py`` already pins ``validate_bbox``
behaviour; this file pins the conversion path that ``validate_bbox`` feeds into.
"""

from __future__ import annotations

import logging

import pytest

from app.services.visual_region_cropper import (
    _DEFAULT_PADDING_PT,
    _MAX_CROP_FILE_SIZE,
    _MAX_CROP_HEIGHT,
    _MAX_CROP_WIDTH,
    _MIN_CROP_HEIGHT,
    _MIN_CROP_WIDTH,
    _PAGE_RENDER_DPI,
    ALLOWED_IMAGE_MIME_TYPES,
    _clamp_bbox,
    convert_bbox,
)
from app.services.visual_region_types import CoordinateSpace


class TestCoordinateSpaceEnum:
    """The four supported coordinate spaces and their string values."""

    def test_pdf_points_value(self):
        assert CoordinateSpace.PDF_POINTS.value == "pdf_points"

    def test_image_pixels_value(self):
        assert CoordinateSpace.IMAGE_PIXELS.value == "image_pixels"

    def test_normalized_1000_value(self):
        assert CoordinateSpace.NORMALIZED_1000.value == "normalized_1000"

    def test_normalized_1_value(self):
        assert CoordinateSpace.NORMALIZED_1.value == "normalized_1"

    def test_members_are_distinct(self):
        values = [s.value for s in CoordinateSpace]
        assert len(values) == len(set(values)) == 4

    def test_is_str_enum(self):
        # StrEnum members compare equal to their string values
        assert CoordinateSpace.PDF_POINTS == "pdf_points"
        assert isinstance(CoordinateSpace.PDF_POINTS, str)

    def test_expected_member_set(self):
        expected = {
            "pdf_points",
            "image_pixels",
            "normalized_1000",
            "normalized_1",
        }
        assert {s.value for s in CoordinateSpace} == expected


class TestModuleConstants:
    """Module-level constants that gate padding, sizing, and MIME filtering."""

    def test_default_padding_pt_is_six(self):
        assert _DEFAULT_PADDING_PT == 6.0

    def test_page_render_dpi_is_150(self):
        assert _PAGE_RENDER_DPI == 150

    def test_max_crop_width_is_4096(self):
        assert _MAX_CROP_WIDTH == 4096

    def test_max_crop_height_is_4096(self):
        assert _MAX_CROP_HEIGHT == 4096

    def test_max_crop_file_size_is_ten_mib(self):
        assert _MAX_CROP_FILE_SIZE == 10 * 1024 * 1024
        assert _MAX_CROP_FILE_SIZE == 10485760

    def test_min_crop_width_is_sixteen(self):
        assert _MIN_CROP_WIDTH == 16

    def test_min_crop_height_is_sixteen(self):
        assert _MIN_CROP_HEIGHT == 16

    def test_allowed_image_mime_types(self):
        assert ALLOWED_IMAGE_MIME_TYPES == frozenset(
            {"image/png", "image/jpeg", "image/webp"}
        )

    def test_allowed_image_mime_types_is_frozen(self):
        # frozenset so it cannot be mutated by accident
        assert isinstance(ALLOWED_IMAGE_MIME_TYPES, frozenset)


class TestConvertBboxImagePixels:
    """image_pixels source: scale_x == scale_y == 1.0, then truncated+clamped."""

    def test_in_bounds_returns_as_int_tuple(self):
        result = convert_bbox((100, 200, 500, 400), "image_pixels", 800, 600)
        assert result == (100, 200, 500, 400)
        assert isinstance(result, tuple)
        assert all(isinstance(v, int) for v in result)

    def test_float_coords_truncated_toward_zero(self):
        # int() truncates toward zero, not rounds
        result = convert_bbox((10.7, 20.7, 100.7, 200.7), "image_pixels", 800, 600)
        assert result == (10, 20, 100, 200)

    def test_float_coords_negative_truncated_toward_zero(self):
        # int(-10.7) == -10 — then clamped to 0 by _clamp_bbox
        result = convert_bbox((-10.7, -20.7, 100.7, 200.7), "image_pixels", 800, 600)
        assert result == (0, 0, 100, 200)

    def test_clamps_x1_to_image_width(self):
        result = convert_bbox((100, 200, 900, 400), "image_pixels", 800, 600)
        assert result == (100, 200, 800, 400)

    def test_clamps_y1_to_image_height(self):
        result = convert_bbox((100, 200, 500, 700), "image_pixels", 800, 600)
        assert result == (100, 200, 500, 600)

    def test_accepts_coordinate_space_enum(self):
        result = convert_bbox(
            (100, 200, 500, 400), CoordinateSpace.IMAGE_PIXELS, 800, 600
        )
        assert result == (100, 200, 500, 400)

    def test_zero_bboxes_clamped_to_zero(self):
        # zero-area source bbox is not rejected here (validate_bbox is the gate)
        result = convert_bbox((0, 0, 0, 0), "image_pixels", 800, 600)
        assert result == (0, 0, 0, 0)

    def test_inverted_bbox_passes_through_inverted(self):
        # Full-path pin: convert_bbox does NOT sort or reject inverted bboxes.
        # An input with x0 > x1 produces an output with x1 < x0 after clamp
        # (x0=900 stays at 900 because no upper clamp, x1=1000 clamps to 800).
        # A refactor that adds sort/reject-on-inverted inside convert_bbox
        # would break this pin.
        result = convert_bbox((900, 700, 1000, 900), "image_pixels", 800, 600)
        assert result == (900, 700, 800, 600)
        # x1 (800) < x0 (900) — inverted result preserved
        assert result[2] < result[0]
        assert result[3] < result[1]


class TestConvertBboxPdfPoints:
    """pdf_points source: scale = image_dim / pdf_dim, or DPI/72 fallback."""

    def test_with_pdf_dims_scales_to_image(self):
        # scale_x = 800/400 = 2.0; scale_y = 600/300 = 2.0
        result = convert_bbox(
            (100, 200, 500, 400), "pdf_points", 800, 600, 400, 300
        )
        assert result == (200, 400, 800, 600)  # 1000, 800 clamped

    def test_with_pdf_dims_non_uniform(self):
        # scale_x = 600/400 = 1.5; scale_y = 400/200 = 2.0
        result = convert_bbox(
            (100, 100, 200, 100), "pdf_points", 600, 400, 400, 200
        )
        assert result == (150, 200, 300, 200)

    def test_with_pdf_dims_truncates_float_scale(self):
        # scale_x = 800/300 = 2.666...; 100*2.666=266.67 -> int=266
        result = convert_bbox(
            (100, 100, 200, 100), "pdf_points", 800, 600, 300, 300
        )
        assert result == (266, 200, 533, 200)

    def test_without_pdf_dims_uses_dpi_fallback(self):
        # Fallback: scale = image / (image * 72 / 150) = 150/72 = 2.0833...
        # 100*2.0833 = 208.33 -> int=208; 200*2.0833=416.67 -> int=416
        # 500*2.0833=1041.67 -> int=1041 -> clamp 800; 400*2.0833=833.33 -> clamp 600
        result = convert_bbox((100, 200, 500, 400), "pdf_points", 800, 600)
        assert result == (208, 416, 800, 600)

    def test_without_pdf_dims_logs_warning(self, caplog):
        with caplog.at_level(logging.WARNING, logger="app.services.visual_region_cropper"):
            convert_bbox((100, 200, 500, 400), "pdf_points", 800, 600)
        assert any(
            "pdf_points without page_pdf dims" in rec.getMessage()
            for rec in caplog.records
        )

    def test_zero_pdf_dims_treated_as_missing(self):
        # page_pdf_width=0 is falsy, so the fallback path is taken
        result_with_zero = convert_bbox(
            (100, 200, 500, 400), "pdf_points", 800, 600, 0, 0
        )
        result_without = convert_bbox(
            (100, 200, 500, 400), "pdf_points", 800, 600
        )
        assert result_with_zero == result_without == (208, 416, 800, 600)

    def test_accepts_coordinate_space_enum(self):
        result = convert_bbox(
            (100, 200, 500, 400),
            CoordinateSpace.PDF_POINTS,
            800,
            600,
            400,
            300,
        )
        assert result == (200, 400, 800, 600)

    def test_clamps_negative_coords(self):
        # negative pdf_points get scaled then clamped to 0
        result = convert_bbox(
            (-50, -50, 500, 400), "pdf_points", 800, 600, 400, 300
        )
        assert result == (0, 0, 800, 600)


class TestConvertBboxNormalized1000:
    """normalized_1000 source: scale = image_dim / 1000.0."""

    def test_basic_conversion(self):
        # scale_x = 800/1000 = 0.8; scale_y = 600/1000 = 0.6
        result = convert_bbox((100, 200, 500, 400), "normalized_1000", 800, 600)
        assert result == (80, 120, 400, 240)

    def test_full_range_maps_to_full_image(self):
        result = convert_bbox((0, 0, 1000, 1000), "normalized_1000", 800, 600)
        # 1000*0.6 = 600.0 -> int=600 (no clamp needed)
        assert result == (0, 0, 800, 600)

    def test_truncates_float(self):
        # scale_x = 987/1000 = 0.987; 100*0.987 = 98.7 -> int=98
        result = convert_bbox((100, 100, 200, 100), "normalized_1000", 987, 600)
        assert result == (98, 60, 197, 60)

    def test_values_above_1000_clamped(self):
        result = convert_bbox((0, 0, 2000, 2000), "normalized_1000", 800, 600)
        assert result == (0, 0, 800, 600)

    def test_negative_normalized_clamped_to_zero(self):
        result = convert_bbox((-100, -100, 500, 400), "normalized_1000", 800, 600)
        assert result == (0, 0, 400, 240)

    def test_accepts_coordinate_space_enum(self):
        result = convert_bbox(
            (100, 200, 500, 400), CoordinateSpace.NORMALIZED_1000, 800, 600
        )
        assert result == (80, 120, 400, 240)


class TestConvertBboxNormalized1:
    """normalized_1 source: scale = image_dim (i.e., image/1.0)."""

    def test_basic_conversion(self):
        result = convert_bbox((0.1, 0.2, 0.5, 0.4), "normalized_1", 800, 600)
        assert result == (80, 120, 400, 240)

    def test_full_range_maps_to_full_image(self):
        result = convert_bbox((0.0, 0.0, 1.0, 1.0), "normalized_1", 800, 600)
        assert result == (0, 0, 800, 600)

    def test_values_above_one_clamped(self):
        result = convert_bbox((0.0, 0.0, 2.0, 2.0), "normalized_1", 800, 600)
        assert result == (0, 0, 800, 600)

    def test_truncates_float(self):
        # scale_x = 800; 0.1234*800 = 98.72 -> int=98; 0.5678*800=454.24->454
        # scale_y = 600; 0.1234*600 = 74.04 -> int=74; 0.5678*600=340.68->340
        result = convert_bbox((0.1234, 0.1234, 0.5678, 0.5678), "normalized_1", 800, 600)
        assert result == (98, 74, 454, 340)

    def test_negative_normalized_clamped_to_zero(self):
        result = convert_bbox((-0.1, -0.2, 0.5, 0.4), "normalized_1", 800, 600)
        assert result == (0, 0, 400, 240)

    def test_accepts_coordinate_space_enum(self):
        result = convert_bbox(
            (0.1, 0.2, 0.5, 0.4), CoordinateSpace.NORMALIZED_1, 800, 600
        )
        assert result == (80, 120, 400, 240)


class TestConvertBboxUnsupportedSpace:
    """Unknown coordinate spaces raise ValueError with a descriptive message."""

    def test_unknown_string_raises(self):
        with pytest.raises(ValueError, match="unsupported coordinate_space"):
            convert_bbox((100, 200, 500, 400), "unknown_space", 800, 600)

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="unsupported coordinate_space"):
            convert_bbox((100, 200, 500, 400), "", 800, 600)

    def test_pdf_points_typo_raises(self):
        with pytest.raises(ValueError, match="unsupported coordinate_space"):
            convert_bbox((100, 200, 500, 400), "pdf_point", 800, 600)

    def test_message_lists_expected_spaces(self):
        with pytest.raises(ValueError) as exc_info:
            convert_bbox((100, 200, 500, 400), "bogus", 800, 600)
        message = str(exc_info.value)
        assert "image_pixels" in message
        assert "pdf_points" in message
        assert "normalized_1000" in message
        assert "normalized_1" in message


class TestClampBbox:
    """_clamp_bbox enforces [0, max] bounds and returns a tuple of ints."""

    # NOTE: clamping is asymmetric. x0/y0 are clamped to the lower bound
    # (max(0, ...)) but not to the upper bound; x1/y1 are clamped to the upper
    # bound (min(max_w, ...)) but not to the lower bound. This is a pinned
    # defect: refactor must preserve the asymmetry or fix it intentionally.

    def test_in_bounds_passthrough(self):
        assert _clamp_bbox(10, 20, 100, 200, 800, 600) == (10, 20, 100, 200)

    def test_negative_x0_clamped_to_zero(self):
        assert _clamp_bbox(-10, 20, 100, 200, 800, 600) == (0, 20, 100, 200)

    def test_negative_y0_clamped_to_zero(self):
        assert _clamp_bbox(10, -20, 100, 200, 800, 600) == (10, 0, 100, 200)

    def test_x1_over_max_clamped_to_max(self):
        assert _clamp_bbox(10, 20, 900, 200, 800, 600) == (10, 20, 800, 200)

    def test_y1_over_max_clamped_to_max(self):
        assert _clamp_bbox(10, 20, 100, 700, 800, 600) == (10, 20, 100, 600)

    def test_x1_exactly_zero_passes_through(self):
        # Boundary of the upper clamp: min(max_w, 0) == 0 — no special-case
        # rejection. Asymmetric clamping is the pinned behaviour.
        assert _clamp_bbox(10, 20, 0, 200, 800, 600) == (10, 20, 0, 200)

    def test_y1_exactly_zero_passes_through(self):
        # Boundary of the upper clamp: min(max_h, 0) == 0 — no special-case
        # rejection. Asymmetric clamping is the pinned behaviour.
        assert _clamp_bbox(10, 20, 100, 0, 800, 600) == (10, 20, 100, 0)

    def test_x0_exactly_max_passes_through(self):
        # Boundary of the lower clamp: max(0, max_w) == max_w — x0 NOT
        # clamped from above. Asymmetric clamping is the pinned behaviour.
        assert _clamp_bbox(800, 20, 100, 200, 800, 600) == (800, 20, 100, 200)

    def test_y0_exactly_max_passes_through(self):
        # Boundary of the lower clamp: max(0, max_h) == max_h — y0 NOT
        # clamped from above. Asymmetric clamping is the pinned behaviour.
        assert _clamp_bbox(10, 600, 100, 200, 800, 600) == (10, 600, 100, 200)

    def test_x1_negative_not_clamped_from_below(self):
        # min(max_w, -50) == -50 — upper clamp does NOT enforce lower bound.
        # Asymmetric clamping is the pinned behaviour.
        assert _clamp_bbox(0, 0, -50, -50, 800, 600) == (0, 0, -50, -50)

    def test_all_negative_clamped_asymmetrically(self):
        # x0/y0 clamped to 0 (lower bound); x1/y1 NOT clamped from below, so
        # min(max_w, -5) == -5. Asymmetric clamping is the pinned behaviour.
        assert _clamp_bbox(-10, -20, -5, -5, 800, 600) == (0, 0, -5, -5)

    def test_all_over_max_clamped_asymmetrically(self):
        # x1/y1 clamped to max (upper bound); x0/y0 NOT clamped from above, so
        # max(0, 900) == 900. Asymmetric clamping is the pinned behaviour.
        assert _clamp_bbox(900, 700, 1000, 900, 800, 600) == (900, 700, 800, 600)

    def test_returns_tuple(self):
        result = _clamp_bbox(10, 20, 100, 200, 800, 600)
        assert isinstance(result, tuple)

    def test_returns_ints(self):
        result = _clamp_bbox(10, 20, 100, 200, 800, 600)
        assert all(isinstance(v, int) for v in result)

    def test_zero_max_dimensions(self):
        # degenerate image: x0/y0 stay positive (no upper clamp), x1/y1 clamp
        # down to 0 (min(0, ...) == 0). Asymmetric clamping is pinned.
        assert _clamp_bbox(10, 20, 100, 200, 0, 0) == (10, 20, 0, 0)

    def test_returns_four_elements(self):
        result = _clamp_bbox(10, 20, 100, 200, 800, 600)
        assert len(result) == 4

    def test_order_preserved_not_sorted(self):
        # x0, y0, x1, y1 — not sorted, just clamped in place
        result = _clamp_bbox(10, 20, 100, 200, 800, 600)
        assert result == (10, 20, 100, 200)
        # does NOT swap inverted coords
        result = _clamp_bbox(100, 200, 10, 20, 800, 600)
        assert result == (100, 200, 10, 20)


class TestConvertBboxReturnType:
    """convert_bbox always returns a tuple of four ints, regardless of input."""

    def test_image_pixels_returns_tuple_of_ints(self):
        result = convert_bbox((100, 200, 500, 400), "image_pixels", 800, 600)
        assert isinstance(result, tuple)
        assert len(result) == 4
        assert all(isinstance(v, int) for v in result)

    def test_normalized_1000_returns_tuple_of_ints(self):
        result = convert_bbox((100, 200, 500, 400), "normalized_1000", 800, 600)
        assert isinstance(result, tuple)
        assert len(result) == 4
        assert all(isinstance(v, int) for v in result)

    def test_normalized_1_returns_tuple_of_ints(self):
        result = convert_bbox((0.1, 0.2, 0.5, 0.4), "normalized_1", 800, 600)
        assert isinstance(result, tuple)
        assert len(result) == 4
        assert all(isinstance(v, int) for v in result)

    def test_pdf_points_with_dims_returns_tuple_of_ints(self):
        result = convert_bbox(
            (100, 200, 500, 400), "pdf_points", 800, 600, 400, 300
        )
        assert isinstance(result, tuple)
        assert len(result) == 4
        assert all(isinstance(v, int) for v in result)


class TestConvertBboxListInputAccepted:
    """convert_bbox accepts list bbox as long as it has four numeric values."""

    def test_list_bbox_works(self):
        # convert_bbox destructures via x0, y0, x1, y1 = bbox — list works
        result = convert_bbox([100, 200, 500, 400], "image_pixels", 800, 600)
        assert result == (100, 200, 500, 400)
